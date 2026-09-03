#!/usr/bin/env python3
"""
Henter sæson-/divisionsstrukturen fra liga.dust2.dk -- gratis metadata,
ingen demoer nødvendige. Se CLAUDE.md: "seasonData med alle sæsoner og
divisioner tilbage til sæson 14".

Bruges til at slå den RIGTIGE division op for et hold (Liga, 1. Division,
2. Division A/B, osv.) -- ikke bare kvalifikationsbracket-navnet, som er
det eneste, downloaderen kan se lige nu. Se note nedenfor om hvorfor det
ikke ændrer noget for de kampe, vi allerede har.

VIGTIGT: sæson 33 (den aktive sæson) har `"data": []` -- der findes ENDNU
INGEN rigtige divisioner for den, fordi de først fastlægges NÅR
kvalifikationerne er færdige. Så lige nu ER kvalifikationsbracket-navnet
("POWER Ligaen S33 Qualifier 3") det mest specifikke, vi kan vide -- det
er ikke en tilnærmelse, det er den fulde information for dette
sæsontrin. Denne fil bliver først nyttig, når sæson 33 rykker videre til
selve divisionerne, eller når man skal slå historik op for tidligere
sæsoner.

Brug:
    python hent_seasondata.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overvaagning import JobFejl, koer_job  # noqa: E402
from downloader.next_data import parse_chunks, find_key  # noqa: E402

ROD = Path(__file__).resolve().parent.parent
SEASONDATA_STI = ROD / "seasondata.json"

BASE_URL = "https://liga.dust2.dk"
USER_AGENT = "Foreningens-scoutingvaerktoej/0.1 (kontakt: Niclasvojens@gmail.com)"


def hent_seasondata() -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    r = session.get(f"{BASE_URL}/kampe", timeout=30)
    r.raise_for_status()
    data = find_key(parse_chunks(r.text), "seasonData")
    if not data:
        raise JobFejl("seasonData tom eller ikke fundet -- HTML-strukturen er sandsynligvis ændret")
    return data


def find_division(seasondata: list[dict], sæson: str, seasonurl_fragment: str) -> dict | None:
    """Slår den rigtige division op for et hold, når man kender sæson-
    nummeret og en seasonUrl-brik (fx holdets bracket-slug). Bruges endnu
    ikke af manifestet -- klar til når sæson 33 får rigtige divisioner."""
    for s in seasondata:
        if s.get("name") != sæson:
            continue
        for d in s.get("data", []):
            if seasonurl_fragment in d.get("seasonUrl", ""):
                return d
    return None


def opdater() -> str:
    data = hent_seasondata()
    SEASONDATA_STI.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Sammenlign som tal, ikke tekst -- "9" > "14" leksikografisk ville give forkert min/max.
    sæson_tal = sorted((int(s["name"]) for s in data if s.get("name", "").isdigit()))
    spænd = f"{sæson_tal[0]}-{sæson_tal[-1]}" if sæson_tal else "ukendt"
    return f"{len(data)} sæsoner hentet ({spænd}), gemt til {SEASONDATA_STI.name}"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    argparse.ArgumentParser().parse_args()  # ingen argumenter endnu, men konsistent med resten af downloader/
    return koer_job("seasondata-scraper", opdater)


if __name__ == "__main__":
    raise SystemExit(main())
