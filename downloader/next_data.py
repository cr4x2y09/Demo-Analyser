"""
Generel læsning af data fra liga.dust2.dk's Next.js flight-payload --
UDEN at parse selve RSC-strukturen (den er bundet til build-id og ændrer
sig ved hver deploy, jf. CLAUDE.md).

Sådan hænger det sammen:
    Next.js sender siden som en stribe <script>self.__next_f.push([1,"..."])
    -tags. Hvert "..." er ét niveaus JSON-streng-escapet fragment af én
    lang, sammenhængende tekst ("flight-teksten"). Den tekst er delt i
    nummererede linjer ("chunks"): `ID:VÆRDI\n`, hvor VÆRDI enten er en
    almindelig JSON-værdi, eller en streng `"$ID"` der PEGER på en anden
    chunk (bruges når Next.js genbruger data flere steder på siden).

    Vigtigt: Next.js kan splitte én lang streng midt i ordet på tværs af
    to <script>-tags, hvis siden er stor. Løsningen er IKKE at lede i den
    rå HTML -- det er at afkode og sammenkæde alle push()-fragmenterne
    FØRST, og først derefter lede efter data i den samlede tekst. Det er
    det denne fil gør.

Brug:
    chunks = parse_chunks(html)
    resultater = find_key(chunks, "resultater")
    vetolog   = find_key(chunks, "vetoLog")
"""

from __future__ import annotations

import json
import re

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)')
_CHUNK_RE = re.compile(r"^([0-9a-zA-Z]+):(.*)$")
_REF_RE = re.compile(r"\$[0-9a-fA-F]+")


def flight_tekst(html: str) -> str:
    """Afkod og sammenkæd alle self.__next_f.push()-fragmenter til én
    sammenhængende tekst. Rejser en enkelt lang streng, selvom Next.js
    har delt den over flere <script>-tags, fordi vi limer de AFKODEDE
    fragmenter sammen i stedet for at søge i den rå HTML."""
    return "".join(json.loads('"' + m.group(1) + '"') for m in _PUSH_RE.finditer(html))


def parse_chunks(html: str) -> dict[str, str]:
    """Split flight-teksten i nummererede chunks: {"3d6": '{"liga":...}', ...}.
    Værdierne er RÅ JSON-tekst (endnu ikke json.loads'et)."""
    chunks: dict[str, str] = {}
    for linje in flight_tekst(html).split("\n"):
        m = _CHUNK_RE.match(linje)
        if m:
            chunks[m.group(1)] = m.group(2)
    return chunks


def chunk_value(chunks: dict[str, str], chunk_id: str):
    """Parser én chunks krop som JSON. Nogle chunks har et bogstav-præfiks
    (fx modul-referencer) som ikke er gyldig JSON -- de er ikke datafelter
    og returnerer bare None."""
    raw = chunks.get(chunk_id)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def resolve(value, chunks: dict[str, str], _dybde: int = 0):
    """Følger rekursivt "$ID"-referencer til deres rigtige værdi."""
    if _dybde > 25:  # sikkerhedsnet mod cirkulære referencer
        return value
    if isinstance(value, str) and _REF_RE.fullmatch(value):
        return resolve(chunk_value(chunks, value[1:]), chunks, _dybde + 1)
    if isinstance(value, list):
        return [resolve(v, chunks, _dybde + 1) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, chunks, _dybde + 1) for k, v in value.items()}
    return value


_MANGLER = object()


def _dyb_soeg(value, noegle: str, chunks: dict[str, str], _dybde: int = 0):
    """Leder efter `noegle` som nøgle i et dict, i alle niveauer -- ikke
    kun top-level. Nødvendigt fordi data nogle gange ligger som en prop
    dybt nede i et serialiseret React-element-træ (fx på /kampe-siden),
    og andre gange som et top-level felt i sit eget datachunk (fx på en
    kampside). Følger "$ID"-referencer undervejs."""
    if _dybde > 25:
        return _MANGLER
    if isinstance(value, str) and _REF_RE.fullmatch(value):
        value = chunk_value(chunks, value[1:])
    if isinstance(value, dict):
        if noegle in value:
            return resolve(value[noegle], chunks)
        for v in value.values():
            fund = _dyb_soeg(v, noegle, chunks, _dybde + 1)
            if fund is not _MANGLER:
                return fund
    elif isinstance(value, list):
        for v in value:
            fund = _dyb_soeg(v, noegle, chunks, _dybde + 1)
            if fund is not _MANGLER:
                return fund
    return _MANGLER


def find_key(chunks: dict[str, str], noegle: str):
    """Find `noegle` hvor den end ligger i chunk-grafen, og returnér
    værdien, fuldt resolvet. Rejser ValueError hvis den ikke findes --
    kald-koden skal fange det og behandle det som "ikke fundet endnu",
    ikke som en fatal fejl (fx et map hvor veto ikke er kørt endnu).

    Tjekker først chunkens RÅ tekst for en billig substring-match, før den
    parser og dybdesøger den -- der er for mange chunks til at parse dem
    alle for hvert opslag."""
    for cid, raw in chunks.items():
        if f'"{noegle}"' not in raw:
            continue
        data = chunk_value(chunks, cid)
        if data is None:
            continue
        fund = _dyb_soeg(data, noegle, chunks)
        if fund is not _MANGLER:
            return fund
    raise ValueError(f"nøgle ikke fundet: {noegle!r}")
