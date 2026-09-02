#!/usr/bin/env python3
"""
Downloaderen: henter kampdata og demoer fra liga.dust2.dk / cdn.overpass.dk.

Kilde-kæden (verificeret manuelt -- ingen login, API-nøgle eller cookies):
    liga.dust2.dk/kampe                -> HTML med JSON: alle kampe (resultater)
    liga.dust2.dk/kampe/{id}/{slug}    -> HTML med JSON: download-links (cdn.overpass.dk)
    cdn.overpass.dk/demos/...          -> GET -> ZIP -> udpak -> .dem

    {id} er kampens challonge_id. {slug} er kosmetisk -- siden svarer med
    samme indhold uanset hvad der står der, så vi generer aldrig et rigtigt
    slug, vi bruger bare challonge_id igen.

JSON'et ligger indlejret i Next.js' flight-payload. Vi parser IKKE
RSC-strukturen -- den er bundet til build-id'et og ændrer sig ved hver
deploy. Se downloader/next_data.py for hvordan vi finder data i den i
stedet.

Brug:
    python hent_demoer.py                # kør en gang, hent alt nyt
    python hent_demoer.py --tjek-disk     # ugentligt: tjek at manifestets filer findes
    python hent_demoer.py --maks 2        # kun til test: stop efter N nye kampe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overvaagning import JobFejl, koer_job  # noqa: E402
from downloader.next_data import parse_chunks, find_key  # noqa: E402

ROD = Path(__file__).resolve().parent.parent
DEMO_MAPPE = ROD / "demoer"
MANIFEST_STI = ROD / "manifest.jsonl"

BASE_URL = "https://liga.dust2.dk"
USER_AGENT = "Foreningens-scoutingvaerktoej/0.1 (kontakt: Niclasvojens@gmail.com)"
PAUSE_SEK = 1.5  # "vær pæn" -- 1-2 sek mellem kald


# --------------------------------------------------------------------------
# Datamodeller
# --------------------------------------------------------------------------

@dataclass
class MapDemo:
    map_num: int
    map_navn: str  # fx "ancient" (uden de_-præfiks, matcher CLAUDE.md's mappestruktur)
    zip_url: str
    score: str | None = None  # fx "13-11", gratis fra mapResults -- ingen demo nødvendig
    vinder_id: str | None = None  # hold_a_id/hold_b_id -- se hvem der vandt via bestem_liga_mappe-siblingen


@dataclass
class Kamp:
    challonge_id: str
    liga_navn: str  # fx "POWER Ligaen S33 Qualifier 3"
    hold_a: str
    hold_b: str
    hold_a_id: str
    hold_b_id: str
    dato: str  # YYYY-MM-DD -- til visning/mappenavne
    tidspunkt: str  # fuldt ISO 8601 -- til præcis kronologisk sortering (analyse-laget)
    state: str
    raw_map_felt: str


def bestem_liga_mappe(liga_navn: str) -> str:
    """Powerligaen og Esportligaen skal ALDRIG blandes -- se CLAUDE.md."""
    navn = liga_navn.lower()
    if "power" in navn:
        return "powerligaen"
    if "esport" in navn:
        return "esportligaen"
    return "andre"  # ukendt liga-type -- hellere en tydelig mappe end at gætte forkert


def vinder_holdnavn(kamp: Kamp, vinder_id: str | None) -> str | None:
    if vinder_id == kamp.hold_a_id:
        return kamp.hold_a
    if vinder_id == kamp.hold_b_id:
        return kamp.hold_b
    return None  # ukendt id -- vis hellere intet end et gæt


def hold_slug(navn: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", navn.lower()).strip("-")
    return s or "ukendt"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def lav_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def hent_kampliste(session: requests.Session) -> list[Kamp]:
    r = session.get(f"{BASE_URL}/kampe", timeout=30)
    r.raise_for_status()
    resultater = find_key(parse_chunks(r.text), "resultater")

    kampe = []
    for k in resultater:
        try:
            dato_obj = k["date_object"][:10]  # "2026-08-29T16:10:00.000Z" -> "2026-08-29"
        except (KeyError, TypeError):
            dato_obj = k.get("dato", "ukendt-dato")
        kampe.append(
            Kamp(
                challonge_id=k["challonge_id"],
                liga_navn=k.get("liga", "ukendt"),
                hold_a=k.get("hold_a", "ukendt"),
                hold_b=k.get("hold_b", "ukendt"),
                hold_a_id=k.get("hold_a_id", ""),
                hold_b_id=k.get("hold_b_id", ""),
                dato=dato_obj,
                tidspunkt=k.get("date_object") or "",
                state=k.get("state", "ukendt"),
                raw_map_felt=k.get("map", ""),
            )
        )
    return kampe


def hent_zip_links(session: requests.Session, challonge_id: str) -> list[MapDemo]:
    """Slug er kosmetisk (verificeret: siden svarer ens uanset slug).

    Bruger mapResults i stedet for at lede efter cdn.overpass.dk-links med
    regex -- giver map-navn, rækkefølge, score og vinder-id'et helt gratis
    i samme hug, uden at skulle regne det ud af zip-filnavnet."""
    r = session.get(f"{BASE_URL}/kampe/{challonge_id}/demoer", timeout=30)
    r.raise_for_status()
    chunks = parse_chunks(r.text)
    map_resultater = find_key(chunks, "mapResults")

    demoer = []
    for i, m in enumerate(map_resultater, start=1):
        demo_urls = m.get("demos") or []
        if not demo_urls:
            continue  # demoen er ikke uploadet endnu -- prøv igen i morgen
        map_navn = (m.get("map") or "").removeprefix("de_")
        if not map_navn:
            continue
        demoer.append(
            MapDemo(
                map_num=i,
                map_navn=map_navn,
                zip_url=demo_urls[0],
                score=m.get("score"),
                vinder_id=m.get("winnerId"),
            )
        )
    return demoer


# --------------------------------------------------------------------------
# Download, udpakning, verificering
# --------------------------------------------------------------------------

def sha256_af_fil(sti: Path) -> str:
    h = hashlib.sha256()
    with sti.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hent_map_demo(session: requests.Session, demo: MapDemo, maalmappe: Path) -> Path:
    """Hent -> pak ud -> verificér -> slet ZIP. Rejser exception ved fejl --
    kaldende kode skal IKKE markere kampen som hentet, hvis dette fejler."""
    maalmappe.mkdir(parents=True, exist_ok=True)
    zip_sti = maalmappe / f"map{demo.map_num}_{demo.map_navn}.zip"
    dem_sti = maalmappe / f"map{demo.map_num}_{demo.map_navn}.dem"

    r = session.get(demo.zip_url, timeout=180, stream=True)
    r.raise_for_status()
    with zip_sti.open("wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)

    with zipfile.ZipFile(zip_sti) as z:
        dem_navne = [n for n in z.namelist() if n.lower().endswith(".dem")]
        if not dem_navne:
            zip_sti.unlink(missing_ok=True)
            raise JobFejl(f"ingen .dem i ZIP: {demo.zip_url}")
        with z.open(dem_navne[0]) as kilde, dem_sti.open("wb") as maal:
            shutil.copyfileobj(kilde, maal)

    zip_sti.unlink()

    MIN_STOERRELSE = 5 * 1024 * 1024  # 5 MB -- en rigtig demo er langt større
    if dem_sti.stat().st_size < MIN_STOERRELSE:
        dem_sti.unlink()
        raise JobFejl(f"demo mistænkeligt lille ({dem_sti.stat().st_size} bytes): {demo.zip_url}")

    return dem_sti


# --------------------------------------------------------------------------
# Manifest -- sandheden, ikke mappestrukturen
# --------------------------------------------------------------------------

def kendte_challonge_ids() -> set[str]:
    if not MANIFEST_STI.exists():
        return set()
    ids = set()
    with MANIFEST_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if linje:
                ids.add(json.loads(linje)["challonge_id"])
    return ids


def skriv_manifest_linje(entry: dict) -> None:
    with MANIFEST_STI.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Hovedjob
# --------------------------------------------------------------------------

def hent_alt(maks_nye: int | None = None) -> str:
    session = lav_session()
    kampe = hent_kampliste(session)
    if not kampe:
        raise JobFejl("0 kampe fundet på liga.dust2.dk/kampe -- HTML-strukturen er sandsynligvis ændret")

    kendte = kendte_challonge_ids()
    nye_kampe = [k for k in kampe if k.challonge_id not in kendte and k.state == "complete"]

    hentet = 0
    fejlet = 0
    for kamp in nye_kampe:
        if maks_nye is not None and hentet >= maks_nye:
            break

        time.sleep(PAUSE_SEK)
        try:
            demoer = hent_zip_links(session, kamp.challonge_id)
        except Exception as e:  # noqa: BLE001
            print(f"  sprunget over ({kamp.hold_a} vs {kamp.hold_b}): kunne ikke hente kampside: {e}")
            fejlet += 1
            continue

        if not demoer:
            print(f"  ingen demo-links endnu for {kamp.hold_a} vs {kamp.hold_b} -- prøver igen i morgen")
            continue

        liga_mappe = bestem_liga_mappe(kamp.liga_navn)
        kampmappe = DEMO_MAPPE / liga_mappe / f"{kamp.dato}_{hold_slug(kamp.hold_a)}-vs-{hold_slug(kamp.hold_b)}"

        hentede_filer = []
        try:
            for demo in demoer:
                time.sleep(PAUSE_SEK)
                dem_sti = hent_map_demo(session, demo, kampmappe)
                hentede_filer.append((demo, dem_sti))
        except Exception as e:  # noqa: BLE001
            print(f"  fejl under download af {kamp.hold_a} vs {kamp.hold_b}: {e} -- kampen markeres IKKE som hentet")
            fejlet += 1
            continue

        skriv_manifest_linje(
            {
                "challonge_id": kamp.challonge_id,
                "liga": liga_mappe,
                "division": kamp.liga_navn,
                "dato": kamp.dato,
                "tidspunkt": kamp.tidspunkt,
                "hold_a": kamp.hold_a,
                "hold_b": kamp.hold_b,
                "kampmappe": str(kampmappe.relative_to(ROD)).replace("\\", "/"),
                "maps": [
                    {
                        "map": demo.map_navn,
                        "fil": str(sti.relative_to(ROD)).replace("\\", "/"),
                        "sha256": sha256_af_fil(sti),
                        "bytes": sti.stat().st_size,
                        "score": demo.score,
                        "vinder": vinder_holdnavn(kamp, demo.vinder_id),
                    }
                    for demo, sti in hentede_filer
                ],
                "hentet_tidspunkt": datetime.now(timezone.utc).isoformat(),
            }
        )
        hentet += 1
        print(f"  hentet: {kamp.hold_a} vs {kamp.hold_b} ({liga_mappe}, {len(hentede_filer)} map(s))")

    return f"{hentet} nye kampe hentet, {fejlet} fejlet, {len(kampe) - len(nye_kampe)} allerede kendt"


def tjek_disk() -> str:
    """Ugentligt tjek: findes filerne fra manifestet faktisk?"""
    if not MANIFEST_STI.exists():
        return "intet manifest endnu"
    mangler = []
    talt = 0
    with MANIFEST_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if not linje:
                continue
            entry = json.loads(linje)
            for m in entry["maps"]:
                talt += 1
                if not (ROD / m["fil"]).exists():
                    mangler.append(m["fil"])
    if mangler:
        raise JobFejl(f"{len(mangler)} af {talt} demoer fra manifestet mangler på disk: {mangler[:10]}")
    return f"{talt} demoer verificeret på disk"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # ældre Python uden reconfigure -- ikke kritisk, kun kosmetisk

    ap = argparse.ArgumentParser()
    ap.add_argument("--tjek-disk", action="store_true", help="kør det ugentlige disk-tjek i stedet for at hente")
    ap.add_argument("--maks", type=int, default=None, help="stop efter N nye kampe (til test)")
    args = ap.parse_args()

    if args.tjek_disk:
        return koer_job("demo-downloader-disktjek", tjek_disk)
    return koer_job("demo-downloader", lambda: hent_alt(maks_nye=args.maks))


if __name__ == "__main__":
    raise SystemExit(main())
