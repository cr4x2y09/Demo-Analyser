#!/usr/bin/env python3
"""
Henter scoreboard (SteamID64, first kills/deaths, trade kills, KAST, osv.)
og round-by-round resultater (vinder, overlevende, årsag) fra kampsiden --
begge dele er gratis metadata, der IKKE kræver at demoen er parset. Se
CLAUDE.md's afsnit om gratis metadata på kampsiden.

Bruger den generelle chunk-resolver i next_data.py til at følge
Next.js-referencerne (`"scoreboard":"$404"` osv.) i stedet for at grave i
den rå HTML.

Brug:
    python hent_kampstats.py
    python hent_kampstats.py --maks 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overvaagning import JobFejl, koer_job  # noqa: E402
from downloader.next_data import parse_chunks, find_key  # noqa: E402

ROD = Path(__file__).resolve().parent.parent
STATS_STI = ROD / "kampstats.jsonl"

BASE_URL = "https://liga.dust2.dk"
USER_AGENT = "Foreningens-scoutingvaerktoej/0.1 (kontakt: Niclasvojens@gmail.com)"
PAUSE_SEK = 1.5

# De felter fra det rå scoreboard-objekt, vi faktisk gemmer -- resten
# (nb1/nb2/.../smokeKills/point/tk osv.) er enten redundante eller ikke
# noget kravspec'en beder om.
SPILLER_FELTER = (
    "steamid",
    "pseudo",
    "rating",
    "hs",
    "nb_kill",
    "death",
    "assist",
    "damage",
    "utility_damage",
    "enemies_flashed",
    "trade_kills",
    "first_kills_t",
    "first_kills_ct",
    "first_deaths_t",
    "first_deaths_ct",
    "kast",
    "rounds",
)


def lav_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def kendte_challonge_ids() -> set[str]:
    if not STATS_STI.exists():
        return set()
    ud = set()
    with STATS_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if linje:
                ud.add(json.loads(linje)["challonge_id"])
    return ud


def skriv_stats_linje(entry: dict) -> None:
    with STATS_STI.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def uddrag_spiller(raw: dict) -> dict:
    return {felt: raw.get(felt) for felt in SPILLER_FELTER}


def hent_kampstats(session: requests.Session, challonge_id: str) -> list[dict]:
    """Én indgang per map: map-navn, score, spillerstatistik for begge
    hold, og runde-for-runde forløb (vinder/overlevende/årsag)."""
    r = session.get(f"{BASE_URL}/kampe/{challonge_id}/stats", timeout=30)
    r.raise_for_status()
    chunks = parse_chunks(r.text)
    scoreboard = find_key(chunks, "scoreboard")

    maps_ud = []
    for map_data in scoreboard:
        if not isinstance(map_data, dict):
            continue
        maps_ud.append(
            {
                "map": (map_data.get("map") or "").lower(),
                "teamA_score": map_data.get("teamA_score"),
                "teamB_score": map_data.get("teamB_score"),
                "teamA_spillere": [uddrag_spiller(p) for p in (map_data.get("teamA") or [])],
                "teamB_spillere": [uddrag_spiller(p) for p in (map_data.get("teamB") or [])],
                "runder": map_data.get("roundOverview") or [],
            }
        )
    return maps_ud


def hent_alt(maks_nye: int | None = None) -> str:
    session = lav_session()
    r = session.get(f"{BASE_URL}/kampe", timeout=30)
    r.raise_for_status()
    kampe = find_key(parse_chunks(r.text), "resultater")
    if not kampe:
        raise JobFejl("0 kampe fundet på liga.dust2.dk/kampe -- HTML-strukturen er sandsynligvis ændret")

    kendte = kendte_challonge_ids()
    nye = [k for k in kampe if k["challonge_id"] not in kendte and k.get("state") == "complete"]

    hentet = 0
    sprunget_over = 0
    for kamp in nye:
        if maks_nye is not None and hentet >= maks_nye:
            break

        time.sleep(PAUSE_SEK)
        try:
            maps_ud = hent_kampstats(session, kamp["challonge_id"])
        except Exception as e:  # noqa: BLE001
            print(f"  ingen stats endnu for {kamp.get('hold_a')} vs {kamp.get('hold_b')}: {e}")
            sprunget_over += 1
            continue

        if not maps_ud:
            sprunget_over += 1
            continue

        skriv_stats_linje(
            {
                "challonge_id": kamp["challonge_id"],
                "liga": kamp.get("liga", "ukendt"),
                "dato": (kamp.get("date_object") or "")[:10],
                # Fuldt tidsstempel -- flere kampe deler ofte samme dato (en
                # spilledag kan have 20+ kampe), så holdout-splittet i
                # analyse/terskler.py skal sortere på klokkeslæt for reelt
                # at skille "nyeste 25%" fra resten. Sorterer korrekt som
                # streng, fordi ISO 8601 er leksikografisk ordnet.
                "tidspunkt": kamp.get("date_object") or "",
                "hold_a": kamp.get("hold_a"),
                "hold_b": kamp.get("hold_b"),
                "maps": maps_ud,
            }
        )
        hentet += 1
        print(f"  stats hentet: {kamp.get('hold_a')} vs {kamp.get('hold_b')} ({len(maps_ud)} map(s))")

    return f"{hentet} nye kampstats hentet, {sprunget_over} sprunget over, {len(kampe) - len(nye)} allerede kendt/ufuldført"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--maks", type=int, default=None, help="stop efter N nye kampe (til test)")
    args = ap.parse_args()
    return koer_job("kampstats-scraper", lambda: hent_alt(maks_nye=args.maks))


if __name__ == "__main__":
    raise SystemExit(main())
