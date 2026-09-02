#!/usr/bin/env python3
"""
Parseren: pakker en enkelt .dem-fil om til Polars-tabeller og cacher
resultatet som Parquet, så vi aldrig parser den samme demo to gange.

Bygger på awpy 2.0.2. Kør parse on demand -- ikke automatisk for alle
demoer i downloaderens mappe. Se CLAUDE.md, afsnit "Parsing".

Brug:
    from parser.parse_demo import parse_og_cache

    tabeller = parse_og_cache(Path("demoer/powerligaen/.../map1_anubis.dem"))
    tabeller["rounds"]       # runde-grænser
    tabeller["ticks"]        # spillerpositioner, nedsamplet til TARGET_HZ
    tabeller["kills"]        # osv.

    python parse_demo.py demoer/.../map1_anubis.dem     # CLI: parse én demo, print et resume

VIGTIGT (endnu ikke verificeret mod rigtige data -- kør på en Nuke/Vertigo-
demo og tjek, før dette bruges i produktion):
    - `tilfoej_etage()` bruger et generisk "find det største hul i
      Z-fordelingen"-heuristik, IKKE en hårdkodet per-map Z-grænse. CLAUDE.md
      giver ikke konkrete tal, og vi har (endnu) ingen Nuke/Vertigo-demoer at
      kalibrere imod. Se docstring på funktionen.
    - `radar_koordinater()` følger formlen fra CLAUDE.md, men map-metadata
      (pos_x/pos_y/scale) skal hentes med `awpy get maps` + `awpy get tris`
      først -- ikke gjort her.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

ROD = Path(__file__).resolve().parent.parent
CACHE_MAPPE = ROD / "parsed"
MANIFEST_STI = ROD / "manifest.jsonl"

TICKRATE = 64  # CS2 GOTV-demoer i denne liga kører 64 tick -- awpy defaulter til 128.
TARGET_HZ = 8  # downsample-mål, jf. CLAUDE.md ("Downsample ticks til 4-8 Hz")

# Maps med to etager -- positioner SKAL splittes på Z, ellers ligger
# B-spillerne oven i A-spillerne i både data og på kortet.
TO_ETAGER = {"de_nuke", "de_vertigo"}


# --------------------------------------------------------------------------
# Cache-nøgle
# --------------------------------------------------------------------------

def sha256_af_fil(sti: Path) -> str:
    h = hashlib.sha256()
    with sti.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_fra_manifest(dem_sti: Path) -> str | None:
    """Genbrug hash'en fra downloaderens manifest, hvis den findes der --
    sparer os for at læse en 200-350 MB fil igennem to gange."""
    if not MANIFEST_STI.exists():
        return None
    rel = str(dem_sti.resolve().relative_to(ROD)).replace("\\", "/")
    with MANIFEST_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if not linje:
                continue
            entry = json.loads(linje)
            for m in entry["maps"]:
                if m["fil"] == rel:
                    return m["sha256"]
    return None


def demo_hash(dem_sti: Path) -> str:
    return hash_fra_manifest(dem_sti) or sha256_af_fil(dem_sti)


# --------------------------------------------------------------------------
# Nedsampling
# --------------------------------------------------------------------------

def downsample_ticks(ticks: pl.DataFrame, tickrate: int = TICKRATE, target_hz: int = TARGET_HZ) -> pl.DataFrame:
    """Behold hver N'te tick, hvor N = tickrate / target_hz (afrundet)."""
    n = max(1, round(tickrate / target_hz))
    return ticks.filter(pl.col("tick") % n == 0)


# --------------------------------------------------------------------------
# Etage-split (Nuke, Vertigo)
# --------------------------------------------------------------------------

def tilfoej_etage(ticks: pl.DataFrame, map_navn: str) -> pl.DataFrame:
    """Tilføjer en "etage"-kolonne (0/1) for maps med to niveauer.

    Ikke en hårdkodet Z-grænse -- CLAUDE.md giver ingen konkrete tal, og der
    er ingen garanti for at samme grænse gælder på tværs af rundetyper eller
    engine-opdateringer. I stedet: sortér de observerede Z-værdier og find
    det STØRSTE hul mellem to nabo-værdier. Det hul er per definition
    skellet mellem "de der står nede" og "de der står oppe", fordi der
    ikke er noget spilbart rum midt i en etageadskillelse.

    Skal verificeres mod en rigtig Nuke- eller Vertigo-demo, før den bruges
    til noget: tjek at spillere kendt for at stå i kælderen/Secret rent
    faktisk lander i etage 0, og A-site/Heaven-spillere i etage 1.
    """
    if map_navn not in TO_ETAGER:
        return ticks.with_columns(pl.lit(0).alias("etage"))

    z_vaerdier = ticks.select("Z").drop_nulls().unique().sort("Z")["Z"].to_list()
    if len(z_vaerdier) < 2:
        return ticks.with_columns(pl.lit(0).alias("etage"))

    stoerste_hul = 0.0
    graense = z_vaerdier[0]
    for a, b in zip(z_vaerdier, z_vaerdier[1:]):
        hul = b - a
        if hul > stoerste_hul:
            stoerste_hul = hul
            graense = (a + b) / 2

    return ticks.with_columns((pl.col("Z") > graense).cast(pl.Int8).alias("etage"))


# --------------------------------------------------------------------------
# Radar-koordinater
# --------------------------------------------------------------------------

def radar_koordinater(df: pl.DataFrame, pos_x: float, pos_y: float, scale: float) -> pl.DataFrame:
    """x_radar = (x - pos_x) / scale ; y_radar = (pos_y - y) / scale.

    pos_x/pos_y/scale kommer fra map-metadata -- hentes med
    `awpy get maps` + `awpy get tris` (ikke automatiseret her endnu)."""
    return df.with_columns(
        ((pl.col("X") - pos_x) / scale).alias("x_radar"),
        ((pos_y - pl.col("Y")) / scale).alias("y_radar"),
    )


# --------------------------------------------------------------------------
# Selve parsingen + cache
# --------------------------------------------------------------------------

TABELLER = ("rounds", "ticks", "kills", "grenades", "smokes", "damages", "bomb", "shots", "infernos")


def _cache_sti(hash_: str) -> Path:
    return CACHE_MAPPE / hash_


def parse_og_cache(dem_sti: Path, tving_reparse: bool = False) -> dict[str, pl.DataFrame]:
    """Parser en demo (eller læser fra cache) og returnerer et dict af
    Polars-tabeller. Cachen ligger i parsed/{sha256}/{tabelnavn}.parquet."""
    dem_sti = Path(dem_sti)
    hash_ = demo_hash(dem_sti)
    cache_dir = _cache_sti(hash_)

    if not tving_reparse and cache_dir.exists() and (cache_dir / "_faerdig").exists():
        return {navn: pl.read_parquet(cache_dir / f"{navn}.parquet") for navn in TABELLER if (cache_dir / f"{navn}.parquet").exists()}

    from awpy import Demo  # importeres her, så resten af filen kan læses/lintes uden awpy installeret

    dem = Demo(str(dem_sti), tickrate=TICKRATE)
    dem.parse()

    map_navn = dem.header.get("map_name", "ukendt")

    tabeller: dict[str, pl.DataFrame] = {"rounds": dem.rounds}
    ticks = downsample_ticks(dem.ticks)
    ticks = tilfoej_etage(ticks, map_navn)
    tabeller["ticks"] = ticks

    for navn in ("kills", "grenades", "smokes", "damages", "bomb", "shots", "infernos"):
        try:
            tabeller[navn] = getattr(dem, navn)
        except Exception:  # noqa: BLE001 -- ikke alle events findes i alle demoer (fx ingen infernos)
            continue

    cache_dir.mkdir(parents=True, exist_ok=True)
    for navn, df in tabeller.items():
        df.write_parquet(cache_dir / f"{navn}.parquet")
    (cache_dir / "_faerdig").write_text(f"map={map_navn}\nkilde={dem_sti}\n", encoding="utf-8")

    return tabeller


def main() -> int:
    if len(sys.argv) != 2:
        print("brug: python parse_demo.py <sti-til.dem>")
        return 1
    sti = Path(sys.argv[1])
    tabeller = parse_og_cache(sti)
    print(f"parset {sti.name}:")
    for navn, df in tabeller.items():
        print(f"  {navn:<10} {df.height:>8} rækker  {df.width:>3} kolonner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
