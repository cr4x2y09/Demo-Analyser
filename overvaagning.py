#!/usr/bin/env python3
"""
Overvaagning af baggrundsjobs.

Sender besked til Discord naar et job har fejlet N gange i traek,
og igen naar det virker paa ny.

Brug:
    from overvaagning import koer_job, JobFejl

    def hent():
        ...
        if ikke_logget_ind:
            raise JobFejl("Login afvist -- cookie udloebet?")
        return f"hentede {antal} demoer"

    koer_job("demo-downloader", hent)
"""

import json
import os
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

# Saet dem som miljoevariabler i stedet for at skrive dem i koden.
WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

# Doedmandsknap: healthchecks.io giver dig en URL. Pinges den ikke
# inden for dit vindue, sender DE dig en mail. Det er den eneste maade
# at opdage at serveren slet ikke koerer.
HEARTBEAT = os.environ.get("HEARTBEAT_URL", "")

GRAENSE = 3          # antal fejl i traek foer der varsles
GENVARSEL_TIMER = 12  # undgaa at spamme naar noget har vaeret nede laenge

STATE_DIR = Path.home() / ".jobstate"


class JobFejl(Exception):
    """Rejs denne naar jobbet teknisk set koerte, men resultatet er forkert."""


def _nu() -> datetime:
    return datetime.now(timezone.utc)


def _laes(fil: Path) -> dict:
    if fil.exists():
        try:
            return json.loads(fil.read_text())
        except json.JSONDecodeError:
            pass
    return {"fejl_i_traek": 0, "sidste_succes": None, "sidst_varslet": None}


def _besked(tekst: str) -> None:
    """Sender til Discord. Maa aldrig selv kaste en exception."""
    if not WEBHOOK:
        print("[ingen webhook konfigureret]\n" + tekst)
        return
    try:
        # Discord tillader 2000 tegn. Klip fra starten, saa den
        # egentlige fejllinje nederst i et traceback overlever.
        if len(tekst) > 1900:
            tekst = "...\n" + tekst[-1900:]
        requests.post(WEBHOOK, json={"content": tekst}, timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"kunne ikke sende besked: {e}")


def _ping_heartbeat(ok: bool) -> None:
    if not HEARTBEAT:
        return
    try:
        url = HEARTBEAT if ok else HEARTBEAT.rstrip("/") + "/fail"
        requests.get(url, timeout=10)
    except Exception:  # noqa: BLE001, S110
        pass


def koer_job(navn: str, funktion: Callable[[], str]) -> int:
    """Koerer funktion() med overvaagning. Returnerer exit-kode."""
    STATE_DIR.mkdir(exist_ok=True)
    fil = STATE_DIR / f"{navn}.json"
    state = _laes(fil)

    try:
        resultat = funktion()
    except Exception:  # noqa: BLE001
        spor = traceback.format_exc()
        state["fejl_i_traek"] += 1
        state["sidste_fejl"] = spor
        antal = state["fejl_i_traek"]

        print(f"FEJL ({antal} i traek):\n{spor}")
        _ping_heartbeat(ok=False)

        # Varsl foerst ved graensen -- enkeltstaaende fejl er ofte
        # bare et netvaerksglitch der retter sig selv naeste nat.
        if antal >= GRAENSE:
            sidst = state.get("sidst_varslet")
            forfaldent = (
                sidst is None
                or _nu() - datetime.fromisoformat(sidst) > timedelta(hours=GENVARSEL_TIMER)
            )
            if forfaldent:
                siden = state.get("sidste_succes") or "aldrig"
                _besked(
                    f"@here **{navn} har fejlet {antal} gange i traek**\n"
                    f"Sidste vellykkede koersel: {siden}\n"
                    f"```\n{spor}\n```"
                )
                state["sidst_varslet"] = _nu().isoformat()

        fil.write_text(json.dumps(state, indent=2))
        return 1

    # Succes
    var_nede = state["fejl_i_traek"] >= GRAENSE
    state.update(fejl_i_traek=0, sidste_succes=_nu().isoformat(),
                 sidst_varslet=None, sidste_fejl=None)
    fil.write_text(json.dumps(state, indent=2))

    print(f"OK: {resultat}")
    _ping_heartbeat(ok=True)

    if var_nede:
        _besked(f"**{navn} koerer igen** \n{resultat}")

    return 0


if __name__ == "__main__":
    # Lille selvtest
    import sys

    def demo_job() -> str:
        if "--fejl" in sys.argv:
            raise JobFejl("Login afvist -- session-cookie udloebet")
        return "hentede 4 nye demoer"

    sys.exit(koer_job("selvtest", demo_job))
