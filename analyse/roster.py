"""
Roster-filter: demoer indgår kun i analysen hvis mindst 3-4 af holdets
NUVÆRENDE femmer var på serveren. Match på SteamID64, aldrig holdnavn --
se CLAUDE.md.

Bygger på kampstats.jsonl (spiller-scoreboards), ikke på parsede demoer,
så det virker allerede nu.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROD = Path(__file__).resolve().parent.parent
STATS_STI = ROD / "kampstats.jsonl"

MIN_OVERLAP = 3  # CLAUDE.md: "mindst 3-4"


def laes_kampstats() -> list[dict]:
    if not STATS_STI.exists():
        return []
    ud = []
    with STATS_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if linje:
                ud.append(json.loads(linje))
    return ud


def _spillere_for_hold(kamp: dict, hold_navn: str) -> set[str]:
    """SteamID64'er for et hold i én kamp (kan spille flere maps -- vi
    samler alle der optrådte)."""
    side = "teamA_spillere" if kamp["hold_a"] == hold_navn else "teamB_spillere"
    ud = set()
    for m in kamp["maps"]:
        for p in m.get(side, []):
            if p.get("steamid"):
                ud.add(p["steamid"])
    return ud


def nuvaerende_roster(kampstats: list[dict], hold_navn: str, seneste_n_kampe: int = 10) -> set[str]:
    """De 5 SteamID64'er der optræder oftest for holdet i de seneste N
    kampe. Simpel "nuværende opstilling"-tilnærmelse -- ingen rigtig
    transfer-liste findes, så vi udleder det af hvem der faktisk spiller."""
    relevante = [k for k in kampstats if hold_navn in (k["hold_a"], k["hold_b"])]
    # tidspunkt (fuldt ISO 8601) frem for dato -- mange kampe deler samme
    # dato (en spilledag kan have 20+ kampe), "dato" alene giver ikke en
    # pålidelig kronologisk rækkefølge.
    relevante.sort(key=lambda k: k.get("tidspunkt") or k["dato"], reverse=True)
    relevante = relevante[:seneste_n_kampe]

    taeller: Counter[str] = Counter()
    for k in relevante:
        for sid in _spillere_for_hold(k, hold_navn):
            taeller[sid] += 1
    return {sid for sid, _ in taeller.most_common(5)}


def kamp_i_roster(kamp: dict, hold_navn: str, roster: set[str], min_overlap: int = MIN_OVERLAP) -> bool:
    """Skal denne kamp indgå i analysen af holdets NUVÆRENDE opstilling?"""
    if not roster:
        return False
    return len(_spillere_for_hold(kamp, hold_navn) & roster) >= min_overlap


def filtrer_paa_roster(kampstats: list[dict], hold_navn: str) -> tuple[list[dict], set[str], int]:
    """Bekvemmeligheds-wrapper: udled roster, filtrér, returnér også hvor
    mange kampe der blev sorteret fra (til "X ældre kampe er udeladt")."""
    roster = nuvaerende_roster(kampstats, hold_navn)
    relevante = [k for k in kampstats if hold_navn in (k["hold_a"], k["hold_b"])]
    beholdt = [k for k in relevante if kamp_i_roster(k, hold_navn, roster)]
    udeladt = len(relevante) - len(beholdt)
    return beholdt, roster, udeladt
