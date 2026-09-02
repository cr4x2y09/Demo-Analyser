#!/usr/bin/env python3
"""
Grundopstilling -- klynger runder efter hvilken SAMLING af callouts
holdets levende spillere står i ved et fast tidspunkt i runden. Det er
kravspec-v1.md's hovedafsnit: "IGL'erne kan selv huske enkeltspillere;
det de ikke kan, er at holde styr på hvordan fem positioner hænger
sammen."

Bygger på parser/parse_demo.py's cachede Parquet-tabeller (rounds + ticks)
for allerede parsede demoer, plus roster-filteret fra analyse/roster.py
(samme princip: match på SteamID64, aldrig holdnavn). Kører KUN på demoer
der allerede er hentet og ligger på disken -- ingen automatisk download
eller parsing herfra, jf. CLAUDE.md: "Parse on demand".

FORENKLING (dokumenteret, ikke skjult): en opstilling identificeres her
ved MÆNGDEN af besatte callouts (fx {"Heaven", "BombsiteA", "CTSpawn",
"Squeaky", "Control"}), ikke ved hvilken SPECIFIK spiller der står hvor.
Det fanger "formen" af opstillingen -- det IGL'erne selv sagde de ikke kan
overskue -- uden at kræve spiller-til-position-tracking på tværs af
runder og kampe. To runder med præcis samme callout-mængde tælles som
samme opstilling; en runde der afviger med bare ét enkelt callout tælles
som en ANDEN opstilling. Det er bevidst strengt for en første udgave --
se ÅBNE punkter nederst.

Brug:
    python -m analyse.opstillinger "MASQ" de_nuke --side ct --sekunder 20
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import polars as pl

ROD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROD))

from analyse.roster import laes_kampstats, nuvaerende_roster  # noqa: E402
from parser.parse_demo import parse_og_cache  # noqa: E402

MANIFEST_STI = ROD / "manifest.jsonl"

# Samme tærskel som analyse/terskler.py's MIN_FOREKOMSTER -- konsistens på
# tværs af analyselaget, selvom dette ikke er en udløser/konsekvens-test.
MIN_FOREKOMSTER = 4


# --------------------------------------------------------------------------
# Manifest -- hvilke .dem-filer findes der for holdet på dette map
# --------------------------------------------------------------------------

def _manifest_kampe() -> list[dict]:
    if not MANIFEST_STI.exists():
        return []
    ud = []
    with MANIFEST_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if linje:
                ud.append(json.loads(linje))
    return ud


def dem_stier_for_hold_map(hold_navn: str, map_navn: str) -> list[Path]:
    """.dem-stier for alle kampe hvor holdet mødtes på map_navn, og filen
    rent faktisk findes på disken (den er git-ignoreret og hentes ikke
    automatisk herfra)."""
    ud = []
    for kamp in _manifest_kampe():
        if hold_navn not in (kamp["hold_a"], kamp["hold_b"]):
            continue
        for m in kamp["maps"]:
            if m["map"] != map_navn:
                continue
            sti = ROD / m["fil"]
            if sti.exists():
                ud.append(sti)
    return ud


# --------------------------------------------------------------------------
# Hvilken side spillede holdets roster, og hvad stod de i ved snapshottet
# --------------------------------------------------------------------------

def _hold_side_per_runde(ticks: pl.DataFrame, roster: set[str]) -> dict[int, str]:
    """For hvert round_num: hvilken side (t/ct) spillede holdets roster på?

    Flertalsafgørelse pr. runde (flest ticks fra roster-spillere på den
    side), i stedet for at kræve at ALLE matcher -- en enkelt forkert
    matchet spiller (fx en substitut) skal ikke vælte hele runden."""
    if not roster:
        return {}
    relevante = ticks.filter(pl.col("steamid").cast(pl.Utf8).is_in(list(roster)))
    if relevante.height == 0:
        return {}
    g = (
        relevante.group_by(["round_num", "side"])
        .agg(pl.len().alias("n"))
        .sort(["round_num", "n"], descending=[False, True])
    )
    ud: dict[int, str] = {}
    for row in g.iter_rows(named=True):
        ud.setdefault(row["round_num"], row["side"])  # første (=højeste n) vinder pr. round_num
    return ud


def _snapshot_tick_per_runde(rounds: pl.DataFrame, ticks: pl.DataFrame, sekunder: int, tickrate: int = 64) -> dict[int, int]:
    """round_num -> nærmeste FAKTISKE tick til (freeze_end + N sekunder).

    Ticks er nedsamplet (parser/parse_demo.py, TARGET_HZ), så det præcise
    måltick findes sjældent -- brug nærmeste indenfor runden i stedet."""
    offset = sekunder * tickrate
    maal = rounds.select(
        pl.col("round_num"),
        (pl.col("freeze_end") + offset).alias("maal_tick"),
        pl.col("end").alias("slut_tick"),
    ).filter(
        # Samme filter som defaults.py: drop runder der sluttede før vores
        # snapshot (typisk hurtige eco-runder) -- de forurener "default".
        pl.col("maal_tick") < pl.col("slut_tick")
    )

    ud = {}
    for r in maal.iter_rows(named=True):
        runde_ticks = ticks.filter(pl.col("round_num") == r["round_num"]).select("tick").unique()
        if runde_ticks.height == 0:
            continue
        naermeste = (
            runde_ticks.with_columns((pl.col("tick") - r["maal_tick"]).abs().alias("_diff"))
            .sort("_diff")
            .head(1)["tick"][0]
        )
        ud[r["round_num"]] = naermeste
    return ud


def _halvdel(round_num: int) -> int:
    # Samme forenkling som analyse/moenstre_runder.py: ingen OT-kampe i
    # datasættet endnu, så runder efter 24 puttes i halvleg 2.
    return 1 if round_num <= 12 else 2


def _kontekst_for_runde(vindere: dict[int, str], round_num: int, egen_side: str) -> str:
    """Let version af kravspec-v1.md's "hvad udløser det": pistol, eller
    resultatet af forrige runde på samme side. Ikke køb/buy-type endnu --
    det kræver current_equip_value, som ikke bliver bedt om i dag."""
    if round_num in (1, 13):
        return "pistol"
    forrige_vinder = vindere.get(round_num - 1)
    if forrige_vinder is None or _halvdel(round_num) != _halvdel(round_num - 1):
        return "ukendt"  # første runde i en halvleg -- ingen "forrige runde" på samme side
    return "efter_sejr" if forrige_vinder == egen_side else "efter_tab"


def opstilling_per_runde(
    rounds: pl.DataFrame, ticks: pl.DataFrame, roster: set[str], side: str, sekunder: int
) -> dict[int, tuple[frozenset[str], str]]:
    """round_num -> (mængden af besatte callouts, kontekst), for de runder
    hvor holdet spillede `side` og mindst én roster-spiller er i live med
    kendt callout ved snapshot-tick'et."""
    sider = _hold_side_per_runde(ticks, roster)
    snapshot_ticks = _snapshot_tick_per_runde(rounds, ticks, sekunder)
    vindere = dict(zip(rounds["round_num"].to_list(), rounds["winner"].to_list()))

    ud: dict[int, tuple[frozenset[str], str]] = {}
    for round_num, maal_tick in snapshot_ticks.items():
        if sider.get(round_num) != side:
            continue
        frame = ticks.filter(
            (pl.col("round_num") == round_num)
            & (pl.col("tick") == maal_tick)
            & (pl.col("side") == side)
            & (pl.col("steamid").cast(pl.Utf8).is_in(list(roster)))
            & (pl.col("health") > 0)
            & (pl.col("place").is_not_null())
            & (pl.col("place") != "")
        )
        pladser = frozenset(frame["place"].to_list())
        if pladser:
            ud[round_num] = (pladser, _kontekst_for_runde(vindere, round_num, side))
    return ud


# --------------------------------------------------------------------------
# Klynge på tværs af alle hentede demoer for holdet
# --------------------------------------------------------------------------

def kør_for_hold_map(hold_navn: str, map_navn: str, side: str, sekunder: int) -> list[dict]:
    """Klynger opstillinger på tværs af ALLE hentede + parsede demoer for
    holdet på dette map, filtreret på nuværende roster (SteamID64)."""
    kampstats = laes_kampstats()
    roster = nuvaerende_roster(kampstats, hold_navn)
    if not roster:
        print(f"Intet roster fundet for {hold_navn!r} i kampstats.jsonl")
        return []

    dem_stier = dem_stier_for_hold_map(hold_navn, map_navn)
    if not dem_stier:
        print(f"Ingen hentede demoer for {hold_navn} på {map_navn} "
              f"(mangler i manifest, eller .dem ikke hentet endnu)")
        return []

    taeller: Counter[frozenset[str]] = Counter()
    kontekst_taeller: dict[frozenset[str], Counter[str]] = {}
    total_runder = 0

    for dem_sti in dem_stier:
        try:
            tabeller = parse_og_cache(dem_sti)
        except Exception as e:  # noqa: BLE001 -- én ødelagt/manglende demo skal ikke vælte resten
            print(f"  sprunget over ({dem_sti.name}): {e}")
            continue

        opstillinger = opstilling_per_runde(tabeller["rounds"], tabeller["ticks"], roster, side, sekunder)
        for pladser, kontekst in opstillinger.values():
            taeller[pladser] += 1
            kontekst_taeller.setdefault(pladser, Counter())[kontekst] += 1
            total_runder += 1

    if total_runder == 0:
        print(f"{hold_navn} på {map_navn} ({side.upper()}): ingen runder matchede roster+side "
              f"({len(dem_stier)} demo(er) forsøgt)")
        return []

    ud = []
    rang = 0
    for pladser, antal in taeller.most_common():
        if antal < MIN_FOREKOMSTER:
            continue
        rang += 1
        ud.append(
            {
                "navn": f"{side.upper()}-setup nr. {rang}",
                "pladser": sorted(pladser),
                "antal": antal,
                "total_runder": total_runder,
                "andel": antal / total_runder,
                "kontekst": dict(kontekst_taeller[pladser]),
            }
        )
    return ud


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("hold", help="holdnavn -- bruges kun til at slå roster op i kampstats.jsonl")
    ap.add_argument("map", help="fx de_nuke")
    ap.add_argument("--side", default="ct", choices=["t", "ct"])
    ap.add_argument("--sekunder", type=int, default=20)
    args = ap.parse_args()

    map_navn = args.map.removeprefix("de_")
    setups = kør_for_hold_map(args.hold, map_navn, args.side, args.sekunder)
    if not setups:
        print("Ingen opstillinger over tærsklen.")
        return 0

    for s in setups:
        print(f"\n{s['navn']} -- {s['antal']} af {s['total_runder']} {args.side.upper()}-runder ({s['andel']:.0%})")
        print(f"  {', '.join(s['pladser'])}")
        kontekst_str = ", ".join(f"{k}: {v}" for k, v in sorted(s["kontekst"].items()))
        print(f"  kontekst: {kontekst_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
