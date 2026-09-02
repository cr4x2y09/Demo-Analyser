#!/usr/bin/env python3
"""
Første rigtige mønstre i analyse-laget -- bygget på round-by-round data fra
kampstats.jsonl (roundOverview), IKKE på parsede demoer. Det betyder de kan
køre og valideres nu, mens parseren venter på en x86-maskine.

To mønstertyper, begge med synlig udløser (score/tid, jf. CLAUDE.md regel 1):

    1. Momentum: vinder de runden efter to tabte i træk?
    2. Pistol-effekt: vinder de 2. runde efter en vundet/tabt pistol?

Hvad dette IKKE er: spatial/utility-baserede mønstre ("de smoker Ramp og
roterer B") kræver spillerpositioner og kastet utility -- det ligger i de
parsede demoer, som parseren (parser/parse_demo.py) endnu ikke har kunnet
køre på denne maskine. Disse to mønstre er bevidst begrænset til det,
round-metadata alene kan vise.

PRÆCISIONS-NOTE: basisraten er splittet per halvleg, ikke ét samlet
gennemsnit. Rundevind-rate er typisk meget forskellig på CT/T-side (se
CLAUDE.md's egne eksempler, som altid sammenligner side-specifikt), og et
hold bliver som regel på én side per halvleg -- så halvleg fungerer som en
praktisk stedfortræder for side, uden at skulle krydsreferere hvilken side
holdet startede på (den info ligger kun i veto-loggens "choose to
start"-linjer, som endnu ikke er tagget med hvilket map de gælder for --
se hent_veto.py). Momentum-udløseren respekterer også halvleg-grænsen: en
"tabsstreak" der spænder over pistol-skiftet (runde 12->13) tælles ikke,
fordi økonomien nulstilles der -- det er ikke momentum, det er en ny start.

KENDT BEGRÆNSNING: ingen kampe i det nuværende datasæt er gået i
overtime, så OT-pistoler (runde 25, 31, ...) er ikke håndteret -- runder
efter 24 puttes i halvleg 2 som en forenkling. Ret det, hvis/når der
kommer en OT-kamp med i datasættet.

Brug:
    python moenstre_runder.py "ECSTATIC"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyse.roster import laes_kampstats, filtrer_paa_roster  # noqa: E402
from analyse.terskler import evaluer, Forekomst, Fund  # noqa: E402


def _halvdel(runde_num: int) -> int:
    return 1 if runde_num <= 12 else 2


def _tidsnoegle(kamp: dict) -> str:
    """Fuldt ISO 8601-tidsstempel til kronologisk sortering i holdout-
    splittet (terskler.py) -- "dato" alene rækker ikke, fordi mange kampe
    deler samme dato (en spilledag kan have 20+ kampe)."""
    return kamp.get("tidspunkt") or kamp["dato"]


def _runde_sekvens(kamp: dict, hold_navn: str) -> list[tuple[str, list[tuple[int, bool]]]]:
    """Per map: (map-navn, [(runde_nr, vandt), ...]) for holdet, sorteret."""
    er_a = kamp["hold_a"] == hold_navn
    ud = []
    for m in kamp["maps"]:
        runder = m.get("runder") or []
        if not runder:
            continue
        sekvens = sorted(
            ((r["round"], (r["winner"] == "A") == er_a) for r in runder),
            key=lambda x: x[0],
        )
        ud.append((m["map"], sekvens))
    return ud


def basisrate_per_halvdel(kampe: list[dict], hold_navn: str) -> dict[int, float]:
    talt = {1: 0, 2: 0}
    vundet = {1: 0, 2: 0}
    for kamp in kampe:
        for _, sekvens in _runde_sekvens(kamp, hold_navn):
            for runde_nr, vandt in sekvens:
                h = _halvdel(runde_nr)
                talt[h] += 1
                vundet[h] += vandt
    return {h: (vundet[h] / talt[h] if talt[h] else 0.0) for h in (1, 2)}


def find_momentum(kampe: list[dict], hold_navn: str, baseline: dict[int, float]) -> list[Fund]:
    """Udløser: har tabt de sidste 2 runder i træk, INDEN for samme
    halvleg (synligt på scoreboardet -- I kan se scoren undervejs).
    Konsekvens: vinder de den næste?"""
    fund = []
    for halvdel in (1, 2):
        forekomster: list[Forekomst] = []
        for kamp in kampe:
            for _, sekvens in _runde_sekvens(kamp, hold_navn):
                rel = [(rn, v) for rn, v in sekvens if _halvdel(rn) == halvdel]
                for i in range(2, len(rel)):
                    if not rel[i - 1][1] and not rel[i - 2][1]:
                        forekomster.append(Forekomst(dato=_tidsnoegle(kamp), konsekvens=rel[i][1]))
        navn = "1. halvleg" if halvdel == 1 else "2. halvleg"
        f = evaluer(
            f"Vinder runden efter to tabte runder i træk ({navn})",
            forekomster,
            baseline_rate=baseline[halvdel],
            detaljer={"antal_kampe": len({k["challonge_id"] for k in kampe}), "halvleg": halvdel},
        )
        if f:
            fund.append(f)
    return fund


def find_pistol_effekt(
    kampe: list[dict], hold_navn: str, baseline: dict[int, float], pistol_runde: int, vundet_pistol: bool
) -> Fund | None:
    """Udløser: vandt/tabte pistolrunden -- synligt for alle. Konsekvens:
    vinder de runden lige efter? Runde 1 = 1. halvleg, runde 13 = 2.
    halvleg -- brug basisraten for den halvleg, ikke et blandet tal."""
    halvdel = _halvdel(pistol_runde)
    forekomster: list[Forekomst] = []
    for kamp in kampe:
        for _, sekvens in _runde_sekvens(kamp, hold_navn):
            pistol = next((v for rn, v in sekvens if rn == pistol_runde), None)
            naeste = next((v for rn, v in sekvens if rn == pistol_runde + 1), None)
            if pistol is None or naeste is None:
                continue
            if pistol == vundet_pistol:
                forekomster.append(Forekomst(dato=_tidsnoegle(kamp), konsekvens=naeste))

    beskrivelse = (
        f"Vinder 2. runde efter vundet pistol (runde {pistol_runde})"
        if vundet_pistol
        else f"Vinder 2. runde efter tabt pistol (runde {pistol_runde})"
    )
    return evaluer(
        beskrivelse,
        forekomster,
        baseline_rate=baseline[halvdel],
        er_pistol=True,
        detaljer={"antal_kampe": len({k["challonge_id"] for k in kampe}), "halvleg": halvdel},
    )


def kør_for_hold(hold_navn: str) -> list[Fund]:
    kampstats = laes_kampstats()
    kampe, roster, udeladt = filtrer_paa_roster(kampstats, hold_navn)
    if not kampe:
        print(f"Ingen kampe matcher et roster for {hold_navn} (eller holdet findes ikke i kampstats.jsonl)")
        return []

    baseline = basisrate_per_halvdel(kampe, hold_navn)
    print(
        f"{hold_navn}: {len(kampe)} kampe i roster-filteret ({udeladt} udeladt), "
        f"basis rundevind-rate 1. halvleg {baseline[1]:.0%} / 2. halvleg {baseline[2]:.0%}"
    )

    fund = list(find_momentum(kampe, hold_navn, baseline))
    for pistol_runde in (1, 13):
        for vundet in (True, False):
            f = find_pistol_effekt(kampe, hold_navn, baseline, pistol_runde, vundet)
            if f:
                fund.append(f)
    return fund


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    if len(sys.argv) != 2:
        print("brug: python moenstre_runder.py <holdnavn>")
        return 1
    fund = kør_for_hold(sys.argv[1])
    if not fund:
        print("Ingen fund over tærsklen.")
        return 0
    for f in fund:
        print(f"\n[{f.tier}] {f.beskrivelse}")
        print(f"  {f.konsekvens_ja} af {f.forekomster} ({f.konsekvens_rate:.0%}) -- basis {f.baseline_rate:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
