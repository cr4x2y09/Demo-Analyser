"""
Den statistiske kerne for analyse-laget. Se CLAUDE.md, afsnittet "Analysen
— principper" -- det afsnit er vigtigere end noget andet i projektet.

Denne fil ved intet om CS2, demoer eller runder. Den tager kun imod en
serie af (udløser-skete, konsekvens-fulgte)-par og afgør om det er et fund
eller støj. Det holder den genbrugelig, uanset hvilket lag der leverer
udløser/konsekvens-data (runde-metadata i dag, spilleres positioner og
utility når parseren kan køre).

Tærskler (CLAUDE.md):
    - Mindst 4 forekomster af udløseren
    - Mindst 70% konsekvens
    - Mindst 25 procentpoint over basisraten
    - Skal overleve de nyeste 25% af kampene (holdout), som søgningen ikke har set
    - Kalibreres per hold ved at køre samme søgning på bevidst blandet data
    - Pistolrunder har lavere krav (kun to per kamp)

Tillidsniveauer (kravspec-v1.md):
    - Bekræftet: holder i holdout-kampene
    - Sandsynligt: stærkt i søgesættet, men for få holdout-kampe til at teste
    - Svagt: over grænsen, men kalibreringskørslen på blandet data producerer
      fund af samme styrke -- kan ikke skelnes fra tilfældighed
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

MIN_FOREKOMSTER = 4
MIN_KONSEKVENS_RATE = 0.70
MIN_AFVIGELSE = 0.25
MIN_FOREKOMSTER_PISTOL = 2  # der er kun to pistolrunder per kamp

MIN_HOLDOUT_FOREKOMSTER = 2  # for få til overhovedet at kunne sige "holder/holder ikke"
KALIBRERINGS_KORSLER = 3000  # antal simulerede kørsler i støj-kalibreringen


@dataclass
class Forekomst:
    """Én observation af udløseren: skete konsekvensen, og hvornår (til
    kronologisk sortering ved holdout-split)."""
    dato: str
    konsekvens: bool


@dataclass
class Fund:
    beskrivelse: str
    forekomster: int
    konsekvens_ja: int
    konsekvens_rate: float
    baseline_rate: float
    tier: str | None  # "bekraeftet" | "sandsynligt" | "svagt" | None (forkastet)
    detaljer: dict = field(default_factory=dict)

    @property
    def afvigelse(self) -> float:
        return self.konsekvens_rate - self.baseline_rate


def _rate(forekomster: list[Forekomst]) -> float:
    if not forekomster:
        return 0.0
    return sum(1 for f in forekomster if f.konsekvens) / len(forekomster)


def _over_graense(forekomster: list[Forekomst], baseline: float, min_forekomster: int) -> bool:
    if len(forekomster) < min_forekomster:
        return False
    rate = _rate(forekomster)
    if rate < MIN_KONSEKVENS_RATE:
        return False
    if rate - baseline < MIN_AFVIGELSE:
        return False
    return True


def _split_holdout(forekomster: list[Forekomst]) -> tuple[list[Forekomst], list[Forekomst]]:
    """Ældste 75% = søgesæt, nyeste 25% = holdout. Sorteret på dato."""
    ordnet = sorted(forekomster, key=lambda f: f.dato)
    skel = max(1, round(len(ordnet) * 0.75))
    return ordnet[:skel], ordnet[skel:]


def _kalibrering_finder_lignende(
    forekomster: list[Forekomst], baseline: float, min_forekomster: int, egen_rate: float
) -> bool:
    """Simulerer "bevidst blandet data": hvis udløseren reelt IKKE havde
    noget med konsekvensen at gøre, ville hver forekomst bare følge
    basisraten uafhængigt af de andre. Træk samme antal forekomster
    tilfældigt fra Bernoulli(baseline) mange gange, og se hvor tit ren
    tilfældighed producerer en rate der er lige så stærk som vores.

    (Ikke det samme som at blande selve udfaldslisten -- det ændrer ikke
    summen og dermed slet ikke raten, uanset rækkefølge.)

    Bruger sin egen, deterministisk seedede Random-instans (udledt af selve
    dataen) i stedet for det globale random-modul. Ellers afhænger
    resultatet af, i hvilken rækkefølge og hvor mange gange andre fund er
    blevet evalueret forinden i samme proces -- to kørsler på nøjagtig
    samme data kunne så ende med forskellig tier, hvilket ikke er
    acceptabelt i en rapport, der skal genereres flere gange."""
    if len(forekomster) < min_forekomster:
        return True  # for lidt data til at sige andet end "kan ikke afvises"

    frø_grundlag = "|".join(f"{f.dato}:{f.konsekvens}" for f in forekomster) + f"|{baseline:.6f}"
    seed = int(hashlib.sha256(frø_grundlag.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)

    n = len(forekomster)
    n_over = 0
    for _ in range(KALIBRERINGS_KORSLER):
        simuleret_rate = sum(1 for _ in range(n) if rng.random() < baseline) / n
        if simuleret_rate >= egen_rate:
            n_over += 1
    # Hvis mere end 5% af de simulerede kørsler er lige så stærke ved ren
    # tilfældighed, er fundet ikke til at skelne fra støj.
    return (n_over / KALIBRERINGS_KORSLER) > 0.05


def evaluer(
    beskrivelse: str,
    forekomster: list[Forekomst],
    baseline_rate: float,
    er_pistol: bool = False,
    detaljer: dict | None = None,
) -> Fund | None:
    """Kør hele rørledningen for ét kandidat-mønster:

    1. Passerer det slet ikke den rå tærskel på HELE datasættet, er det
       ikke et fund -- støj, vises ikke.
    2. Kalibrering: er styrken til at skelne fra ren tilfældighed (en
       simuleret "bevidst blandet" baseline)?
    3. Test mod holdout (nyeste 25%, som søgningen ikke har set): holder
       mønsteret stadig DER (egen, lavere mindstegrænse, for holdout er
       naturligt en mindre bid) -- "bekræftet". For få kampe i holdout til
       overhovedet at kunne sige noget -- "sandsynligt". Bliver det
       direkte modbevist i holdout -- ikke et ægte mønster, returnér None."""
    min_forekomster = MIN_FOREKOMSTER_PISTOL if er_pistol else MIN_FOREKOMSTER

    if not _over_graense(forekomster, baseline_rate, min_forekomster):
        return None

    def _lav_fund(tier: str) -> Fund:
        return Fund(
            beskrivelse=beskrivelse,
            forekomster=len(forekomster),
            konsekvens_ja=sum(1 for f in forekomster if f.konsekvens),
            konsekvens_rate=_rate(forekomster),
            baseline_rate=baseline_rate,
            tier=tier,
            detaljer=detaljer or {},
        )

    if _kalibrering_finder_lignende(forekomster, baseline_rate, min_forekomster, _rate(forekomster)):
        return _lav_fund("svagt")

    _, holdout = _split_holdout(forekomster)
    if len(holdout) < MIN_HOLDOUT_FOREKOMSTER:
        return _lav_fund("sandsynligt")

    if _over_graense(holdout, baseline_rate, MIN_HOLDOUT_FOREKOMSTER):
        return _lav_fund("bekraeftet")

    return None  # testet mod holdout og modbevist -- ikke et ægte mønster
