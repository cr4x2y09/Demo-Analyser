#!/usr/bin/env python3
"""
Henter veto-logs (map-ban/pick/side-valg) fra liga.dust2.dk.

Kræver INGEN demoer -- veto sker før kampen overhovedet startes, så dette
kan køre for alle kampe uanset om demoerne findes endnu. Se CLAUDE.md's
afsnit om gratis metadata på kampsiden, og kravspec-v1.md's punkt 6:
"Map veto -- kræver ingen demoer, kan bygges først."

vetoLog-feltet på kampsiden er en almindelig tekstlog, ikke en indlejret
struktur -- ingen grund til at følge Next.js' reference-kæder for at få
fat i den. Eksempel på en linje:

    17:58:37 - ECSTATIC removed Dust2
    17:59:00 - WAZABI choose to start T
    17:59:56 - Inferno  was left over

Brug:
    python hent_veto.py
    python hent_veto.py --maks 5     # til test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overvaagning import JobFejl, koer_job  # noqa: E402
from downloader.next_data import parse_chunks, find_key  # noqa: E402

ROD = Path(__file__).resolve().parent.parent
VETO_STI = ROD / "veto.jsonl"

BASE_URL = "https://liga.dust2.dk"
USER_AGENT = "Foreningens-scoutingvaerktoej/0.1 (kontakt: Niclasvojens@gmail.com)"
PAUSE_SEK = 1.5


def lav_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def parse_veto_log(raw: str, hold_a: str, hold_b: str) -> list[dict]:
    """Tolker den frietekst-veto-log linje for linje. Matcher holdnavne
    eksplicit (i stedet for en generisk \\S+ i et regex), fordi rigtige
    holdnavne kan indeholde mellemrum (fx "Albertslund Esport")."""
    traek: list[dict] = []
    for linje in raw.split("\n"):
        linje = linje.strip()
        m = re.match(r"^(\d{2}:\d{2}:\d{2}) - (.+)$", linje)
        if not m:
            continue
        tid, rest = m.group(1), m.group(2).strip()

        hold = None
        for kandidat in (hold_a, hold_b):
            if rest.startswith(kandidat + " "):
                hold = kandidat
                rest = rest[len(kandidat) :].strip()
                break

        if hold and rest.startswith("removed "):
            traek.append({"tid": tid, "hold": hold, "handling": "banned", "map": rest[len("removed ") :].strip()})
        elif hold and rest.startswith("picked "):
            traek.append({"tid": tid, "hold": hold, "handling": "picked", "map": rest[len("picked ") :].strip()})
        elif hold and rest.startswith("choose to start "):
            traek.append({"tid": tid, "hold": hold, "handling": "side_valg", "side": rest[len("choose to start ") :].strip()})
        elif "was left over" in rest:
            traek.append({"tid": tid, "hold": None, "handling": "left_over", "map": rest.split("was left over")[0].strip()})
        # ukendt linjeformat -- spring stille over frem for at gætte forkert
    return traek


def kendte_challonge_ids() -> set[str]:
    if not VETO_STI.exists():
        return set()
    ud = set()
    with VETO_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if linje:
                ud.add(json.loads(linje)["challonge_id"])
    return ud


def skriv_veto_linje(entry: dict) -> None:
    with VETO_STI.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def hent_alt(maks_nye: int | None = None) -> str:
    session = lav_session()
    r = session.get(f"{BASE_URL}/kampe", timeout=30)
    r.raise_for_status()
    kampe = find_key(parse_chunks(r.text), "resultater")
    if not kampe:
        raise JobFejl("0 kampe fundet på liga.dust2.dk/kampe -- HTML-strukturen er sandsynligvis ændret")

    kendte = kendte_challonge_ids()
    nye = [k for k in kampe if k["challonge_id"] not in kendte]

    hentet = 0
    sprunget_over = 0
    for kamp in nye:
        if maks_nye is not None and hentet >= maks_nye:
            break

        time.sleep(PAUSE_SEK)
        try:
            side = session.get(f"{BASE_URL}/kampe/{kamp['challonge_id']}/veto", timeout=30)
            side.raise_for_status()
            raw_log = find_key(parse_chunks(side.text), "vetoLog")
        except Exception as e:  # noqa: BLE001
            print(f"  ingen veto-log endnu for {kamp.get('hold_a')} vs {kamp.get('hold_b')}: {e}")
            sprunget_over += 1
            continue

        traek = parse_veto_log(raw_log, kamp.get("hold_a", ""), kamp.get("hold_b", ""))
        if not traek:
            sprunget_over += 1
            continue

        skriv_veto_linje(
            {
                "challonge_id": kamp["challonge_id"],
                "liga": kamp.get("liga", "ukendt"),
                "dato": (kamp.get("date_object") or "")[:10],
                "tidspunkt": kamp.get("date_object") or "",  # se hent_kampstats.py for hvorfor
                "hold_a": kamp.get("hold_a"),
                "hold_b": kamp.get("hold_b"),
                "traek": traek,
            }
        )
        hentet += 1
        print(f"  veto hentet: {kamp.get('hold_a')} vs {kamp.get('hold_b')} ({len(traek)} træk)")

    return f"{hentet} nye veto-logs hentet, {sprunget_over} sprunget over, {len(kampe) - len(nye)} allerede kendt"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--maks", type=int, default=None, help="stop efter N nye kampe (til test)")
    args = ap.parse_args()
    return koer_job("veto-scraper", lambda: hent_alt(maks_nye=args.maks))


if __name__ == "__main__":
    raise SystemExit(main())
