#!/usr/bin/env python3
"""
Web-laget: Streamlit-app der viser modstanderrapporter.

Login håndteres af Cloudflare Access foran hele siden (se CLAUDE.md) --
denne app implementerer bevidst IKKE sin egen brugerhåndtering.

Status: "Mønstre" viser rigtige, statistisk validerede fund fra
analyse/moenstre_runder.py (runde-niveau: momentum, pistol-effekt).
"Grundopstilling" viser klyngede positionsmønstre fra
analyse/opstillinger.py (kræver parsede demoer -- se den fil for
forenklinger). Spatiale mønstre ud over grundopstilling ("smoker de Ramp,
roterer B-anchoren") er stadig ikke skrevet.

Kør (fra projektroden):
    pip install -r web/requirements.txt
    streamlit run web/app.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import streamlit as st

ROD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROD))  # så "analyse.*" kan importeres uanset hvorfra streamlit køres

from analyse.moenstre_runder import kør_for_hold  # noqa: E402
from analyse.opstillinger import kør_for_hold_map as opstillinger_for_hold_map  # noqa: E402
from analyse.roster import laes_kampstats as laes_kampstats_raa, filtrer_paa_roster  # noqa: E402

MANIFEST_STI = ROD / "manifest.jsonl"
VETO_STI = ROD / "veto.jsonl"
STATS_STI = ROD / "kampstats.jsonl"
CSS_STI = Path(__file__).resolve().parent / "static" / "rapport.css"


@dataclass
class KampEntry:
    challonge_id: str
    liga: str
    division: str
    dato: str
    hold_a: str
    hold_b: str
    kampmappe: str
    maps: list[dict]

    @property
    def map_navne(self) -> list[str]:
        return [m["map"] for m in self.maps]

    def modstander(self, hold: str) -> str:
        return self.hold_b if hold == self.hold_a else self.hold_a


@st.cache_data(ttl=60)
def laes_manifest() -> list[KampEntry]:
    """Cached i 60 sek, så vi ikke genlæser filen ved hvert widget-klik --
    men stadig opdages nye kampe kort efter downloaderen har kørt."""
    if not MANIFEST_STI.exists():
        return []
    ud = []
    with MANIFEST_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if not linje:
                continue
            d = json.loads(linje)
            ud.append(
                KampEntry(
                    challonge_id=d["challonge_id"],
                    liga=d["liga"],
                    division=d["division"],
                    dato=d["dato"],
                    hold_a=d["hold_a"],
                    hold_b=d["hold_b"],
                    kampmappe=d["kampmappe"],
                    maps=d["maps"],
                )
            )
    return ud


@dataclass
class VetoEntry:
    challonge_id: str
    liga: str  # OBS: her er "liga" divisionsnavnet (fx "POWER Ligaen S33 Qualifier 3"),
    dato: str  # ikke powerligaen/esportligaen-mappen -- se hent_veto.py.
    hold_a: str
    hold_b: str
    traek: list[dict]


@st.cache_data(ttl=60)
def laes_veto() -> list[VetoEntry]:
    if not VETO_STI.exists():
        return []
    ud = []
    with VETO_STI.open("r", encoding="utf-8") as f:
        for linje in f:
            linje = linje.strip()
            if not linje:
                continue
            d = json.loads(linje)
            ud.append(VetoEntry(d["challonge_id"], d["liga"], d["dato"], d["hold_a"], d["hold_b"], d["traek"]))
    return ud


def veto_opsummering(veto_kampe: list[VetoEntry], hold: str) -> dict:
    """Per map: hvor tit holdets FØRSTE bandlysning ramte det map, og hvor
    tit de valgte det. "Vis altid nævneren" -- se CLAUDE.md."""
    relevante = [v for v in veto_kampe if hold in (v.hold_a, v.hold_b)]

    foerste_ban: dict[str, int] = {}
    picks: dict[str, int] = {}
    kampe_med_ban = 0
    kampe_med_pick = 0

    for v in relevante:
        egne_bans = sorted(
            (t for t in v.traek if t["hold"] == hold and t["handling"] == "banned"),
            key=lambda t: t["tid"],
        )
        if egne_bans:
            kampe_med_ban += 1
            map_navn = egne_bans[0]["map"]
            foerste_ban[map_navn] = foerste_ban.get(map_navn, 0) + 1

        egne_picks = [t for t in v.traek if t["hold"] == hold and t["handling"] == "picked"]
        if egne_picks:
            kampe_med_pick += 1
        for p in egne_picks:
            picks[p["map"]] = picks.get(p["map"], 0) + 1

    return {
        "kampe_total": len(relevante),
        "kampe_med_ban": kampe_med_ban,
        "kampe_med_pick": kampe_med_pick,
        "foerste_ban": foerste_ban,
        "picks": picks,
    }


def hold_i_liga(kampe: list[KampEntry], liga: str) -> list[str]:
    hold = set()
    for k in kampe:
        if k.liga == liga:
            hold.add(k.hold_a)
            hold.add(k.hold_b)
    return sorted(hold)


def maps_for_hold(kampe: list[KampEntry], liga: str, hold: str) -> list[str]:
    maps = set()
    for k in kampe:
        if k.liga == liga and hold in (k.hold_a, k.hold_b):
            maps.update(k.map_navne)
    return sorted(maps)


def kampe_for_hold_map(kampe: list[KampEntry], liga: str, hold: str, map_navn: str) -> list[KampEntry]:
    ud = [
        k
        for k in kampe
        if k.liga == liga and hold in (k.hold_a, k.hold_b) and map_navn in k.map_navne
    ]
    return sorted(ud, key=lambda k: k.dato)


def esc(tekst: str) -> str:
    return tekst.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@st.cache_data(ttl=600, show_spinner="Analyserer grundopstillinger (kan tage lidt tid, hvis en demo skal parses for første gang)...")
def grundopstillinger(hold: str, map_navn: str) -> dict[str, list[dict]]:
    """CT- og T-side opstillinger for holdet på dette map, se
    analyse/opstillinger.py. Cachet længere (10 min) end resten af siden,
    fordi parsing af en ny demo kan tage adskillige minutter -- selve
    parse-resultatet cachet permanent som Parquet på disk (se
    parser/parse_demo.py), så det kun er langsomt allerførste gang."""
    return {
        "ct": opstillinger_for_hold_map(hold, map_navn, "ct", sekunder=20),
        "t": opstillinger_for_hold_map(hold, map_navn, "t", sekunder=20),
    }


@st.cache_data(ttl=60)
def spillerprofiler(hold: str) -> list[dict]:
    """Rigtige, aggregerede skydetal fra kampstats.jsonl for holdets
    nuværende roster (SteamID64-filter, se analyse/roster.py). Summerer
    rå tællere på tværs af maps, før procenter regnes ud -- ikke et
    gennemsnit af procenter, som ville vægte korte maps for højt."""
    kampstats = laes_kampstats_raa()
    kampe, roster, _ = filtrer_paa_roster(kampstats, hold)

    agg: dict[str, dict] = {}
    for kamp in kampe:
        side = "teamA_spillere" if kamp["hold_a"] == hold else "teamB_spillere"
        for m in kamp["maps"]:
            for p in m.get(side, []):
                sid = p.get("steamid")
                if sid not in roster:
                    continue
                a = agg.setdefault(
                    sid,
                    {"pseudo": p.get("pseudo"), "maps": 0, "rounds": 0, "nb_kill": 0, "death": 0,
                     "hs": 0, "kast": 0, "trade_kills": 0, "first_kills_t": 0, "first_kills_ct": 0,
                     "ratings": []},
                )
                a["maps"] += 1
                for felt in ("rounds", "nb_kill", "death", "hs", "kast", "trade_kills", "first_kills_t", "first_kills_ct"):
                    a[felt] += p.get(felt) or 0
                try:
                    if p.get("rating") is not None:
                        a["ratings"].append(float(p["rating"]))
                except (TypeError, ValueError):
                    pass

    ud = []
    for sid, a in agg.items():
        ud.append(
            {
                "steamid": sid,
                "pseudo": a["pseudo"] or sid,
                "maps": a["maps"],
                "rating": (sum(a["ratings"]) / len(a["ratings"])) if a["ratings"] else 0.0,
                "hs_pct": (a["hs"] / a["nb_kill"]) if a["nb_kill"] else 0.0,
                "kast_pct": (a["kast"] / a["rounds"]) if a["rounds"] else 0.0,
                "kd": (a["nb_kill"] / a["death"]) if a["death"] else 0.0,
                "first_kills": a["first_kills_t"] + a["first_kills_ct"],
                "trade_kills": a["trade_kills"],
            }
        )
    ud.sort(key=lambda p: -p["rating"])
    return ud


# --------------------------------------------------------------------------
# Sider
# --------------------------------------------------------------------------

def byg_rapport_html(kampe_alle: list[KampEntry], veto_alle: list[VetoEntry], liga: str, hold: str, map_navn: str) -> str:
    """Bygger rapportens indre HTML som én streng -- genbruges både til
    visning på siden og til offline-download (se CLAUDE.md: "Rapporten
    skal også kunne downloades og læses offline")."""
    kampe = kampe_for_hold_map(kampe_alle, liga, hold, map_navn)
    datoer = sorted(k.dato for k in kampe)
    periode = f"{datoer[0]} – {datoer[-1]}" if datoer else "—"

    dele = [
        f"""
        <div class="wrap">
        <header class="top">
          <h1>{esc(hold)} <i>/ {esc(map_navn.capitalize())}</i></h1>
          <p>Sådan forsvarer de</p>
          <div class="meta">
            <div><b>{len(kampe)}</b><span>kampe fundet</span></div>
            <div><b>{periode}</b><span>periode</span></div>
            <div><b>{esc(liga.capitalize())}</b><span>liga</span></div>
            <div><b>{date.today().strftime('%d. %b').lstrip('0')}</b><span>genereret</span></div>
          </div>
          <div class="warn">
            <b>Delvis analyse.</b> Downloaderen har fundet {len(kampe)} kampe med
            {esc(hold)} på {esc(map_navn.capitalize())} i {esc(liga)}. Veto, spillerstats,
            runde-mønstre (momentum/pistol) og grundopstilling er rigtige og statistisk
            validerede -- men bygger typisk på for få kampe endnu til at vise noget.
            Spatiale mønstre ud over grundopstilling ("smoker de Ramp, roterer B-anchoren")
            er ikke skrevet endnu.
          </div>
        </header>
        """
    ]

    dele.append('<section><h2>Fundne kampe</h2>')
    if kampe:
        rows = "".join(
            f"<tr><td class='big'>{esc(k.dato)}</td>"
            f"<td>{esc(k.modstander(hold) if hold in (k.hold_a, k.hold_b) else '')}</td>"
            f"<td>{esc(k.division)}</td>"
            f"<td class='r'>{len(k.maps)} map(s)</td></tr>"
            for k in kampe
        )
        dele.append(
            f"""<table><thead><tr><th>Dato</th><th>Modstander</th>
            <th>Turnering</th><th class="r">Maps i alt</th></tr></thead>
            <tbody>{rows}</tbody></table>"""
        )
    else:
        dele.append('<p class="lede">Ingen kampe fundet.</p>')
    dele.append("</section>")

    dele.append('<section><h2>Veto</h2>')
    opsum = veto_opsummering(veto_alle, hold)
    if opsum["kampe_total"]:
        dele.append(f'<p class="lede">Fra {opsum["kampe_total"]} kampe. Kræver ingen demoer.</p>')
        alle_maps = sorted(set(opsum["foerste_ban"]) | set(opsum["picks"]))
        rows = []
        for m in alle_maps:
            ban_n = opsum["foerste_ban"].get(m, 0)
            pick_n = opsum["picks"].get(m, 0)
            ban_str = f"{ban_n} af {opsum['kampe_med_ban']}" if ban_n else "—"
            pick_str = f"{pick_n} af {opsum['kampe_med_pick']}" if pick_n else "—"
            rows.append(f"<tr><td class='big'>{esc(m)}</td><td class='r'>{ban_str}</td><td class='r'>{pick_str}</td><td class='r'>—</td></tr>")
        dele.append(
            f"""<table><thead><tr><th>Map</th><th class="r">Banner først</th>
            <th class="r">Vælger</th><th class="r">Winrate</th></tr></thead>
            <tbody>{''.join(rows)}</tbody></table>
            <p class="after">Winrate pr. map er ikke koblet på endnu -- kræver at
            mapResults hentes (se downloader/hent_veto.py).</p>"""
        )
    else:
        dele.append('<p class="lede">Ingen veto-data fundet for dette hold endnu.</p>')
    dele.append("</section>")

    dele.append('<section><h2>Grundopstilling</h2>')
    dele.append(
        '<p class="lede">Opstillinger klynges efter hvilke callouts holdets nuværende '
        "roster (SteamID64-filtreret) står i 20 sekunder inde i runden. Kræver mindst "
        "4 identiske forekomster for at blive vist. Se analyse/opstillinger.py.</p>"
    )
    opstillinger = grundopstillinger(hold, map_navn)
    alle_setups = opstillinger.get("ct", []) + opstillinger.get("t", [])
    if alle_setups:
        KONTEKST_NAVN = {
            "pistol": "pistol", "efter_sejr": "efter sejr",
            "efter_tab": "efter tab", "ukendt": "øvrige",
        }
        for s in alle_setups:
            chips = "".join(f'<span class="chip">{esc(p)}</span>' for p in s["pladser"])
            kontekst_str = " · ".join(
                f"<b>{v}</b> {KONTEKST_NAVN.get(k, k)}"
                for k, v in sorted(s["kontekst"].items(), key=lambda kv: -kv[1])
            )
            dele.append(
                f"""<article class="setup">
                <div class="setup-head">
                  <h3>{esc(s['navn'])}</h3>
                  <p class="pct">{s['andel']:.0%} <small>{s['antal']} af {s['total_runder']}</small></p>
                </div>
                <div class="chips">{chips}</div>
                <p class="ctx">{kontekst_str or '—'}</p>
                </article>"""
            )
    else:
        dele.append(
            '<div class="warn">Ingen opstillinger over tærsklen endnu -- kræver flere '
            "hentede og parsede demoer for dette hold på dette map (mindst 4 identiske "
            "positionsmønstre). Se analyse/opstillinger.py.</div>"
        )
    dele.append("</section>")

    dele.append('<section><h2>Mønstre</h2>')
    dele.append(
        '<p class="lede">Fra runde-udfald (score, pistol, momentum) -- endnu ikke fra '
        "spillerpositioner eller utility, det kræver parseren. Se analyse/moenstre_runder.py.</p>"
    )
    fund = kør_for_hold(hold)
    if fund:
        tier_klasse = {"bekraeftet": "ok", "sandsynligt": "maybe", "svagt": "weak"}
        tier_navn = {"bekraeftet": "Bekræftet", "sandsynligt": "Sandsynligt", "svagt": "Svagt"}
        for f in fund:
            dele.append(
                f"""<article class="find {tier_klasse[f.tier]}">
                <p class="tier">{tier_navn[f.tier]}</p>
                <h3>{esc(f.beskrivelse)}</h3>
                <div class="body">
                  <div class="stat">
                    <p class="frac">{f.konsekvens_ja} <small>af</small> {f.forekomster}</p>
                    <div class="bar">
                      <div class="track"><i style="width:{f.konsekvens_rate*100:.0f}%"></i>
                      <u style="left:{f.baseline_rate*100:.0f}%"></u></div>
                      <div class="scale"><span>{f.konsekvens_rate:.0%}</span><span>normalt {f.baseline_rate:.0%}</span></div>
                    </div>
                  </div>
                  <p class="note">Baseret på {f.detaljer.get('antal_kampe', '?')} kampe med den nuværende opstilling.</p>
                </div></article>"""
            )
    else:
        dele.append('<div class="warn">Ingen fund over tærsklen for dette hold endnu.</div>')
    dele.append("</section>")

    dele.append('<section><h2>Spillerne</h2>')
    dele.append('<p class="lede">Rigtige skydetal fra kampstats.jsonl, roster-filtreret på SteamID64. Adfærdsdelen (rolle, positioner, afstand til holdkammerater) kræver parseren.</p>')
    profiler = spillerprofiler(hold)
    if profiler:
        for p in profiler:
            dele.append(
                f"""<article class="pl">
                <h3>{esc(p['pseudo'])}</h3>
                <p class="role">{p['maps']} maps med nuværende opstilling</p>
                <p class="aim">{p['rating']:.2f} rating · {p['hs_pct']:.0%} HS · {p['kd']:.2f} K/D ·
                {p['kast_pct']:.0%} KAST · {p['first_kills']} first kills · {p['trade_kills']} trade kills</p>
                </article>"""
            )
    else:
        dele.append('<div class="warn">Ingen spillerdata fundet endnu.</div>')
    dele.append("</section>")

    dele.append(
        """<footer>
        <h2>Om denne side</h2>
        <p>Kamplisten ovenfor kommer direkte fra downloaderens manifest
        (<code>manifest.jsonl</code>), uden analyse. Veto, spillerstats,
        runde-mønstre og grundopstilling er analyseret -- se hver sektions
        egen note om hvad der (endnu) ikke er dækket.</p>
        </footer>
        </div>"""
    )
    return "\n".join(dele)


def byg_standalone_html(indhold: str, titel: str) -> str:
    """Pakker rapport-HTML'en ind i en selvstændig fil med indlejret CSS,
    så den kan gemmes og læses offline -- samme princip som
    eksempel-rapport.html."""
    css = CSS_STI.read_text(encoding="utf-8") if CSS_STI.exists() else ""
    return f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(titel)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
{indhold}
</body>
</html>
"""


def vis_rapport(kampe_alle: list[KampEntry], veto_alle: list[VetoEntry], liga: str, hold: str, map_navn: str) -> None:
    html = byg_rapport_html(kampe_alle, veto_alle, liga, hold, map_navn)
    st.markdown(html, unsafe_allow_html=True)

    standalone = byg_standalone_html(html, f"{hold} — {map_navn.capitalize()} — Modstanderrapport")
    st.download_button(
        "⬇ Download rapport som HTML (læs offline)",
        data=standalone,
        file_name=f"{hold_slug_web(hold)}-{map_navn}-rapport.html",
        mime="text/html",
    )


def hold_slug_web(navn: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", navn.lower()).strip("-") or "hold"


def main() -> None:
    st.set_page_config(page_title="Modstanderrapport", layout="wide")
    if CSS_STI.exists():
        st.markdown(f"<style>{CSS_STI.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

    # rapport.css forudsætter Archivo-fonten, men linker den ikke selv --
    # byg_standalone_html() gør det for offline-downloadet, men den LIVE
    # side manglede den, og faldt derfor stille tilbage til system-sans.
    # Skjuler også Streamlits eget dev-værktøjslinje (Deploy/hamburger) og
    # gør sidebaren mørk, så det ligner et rigtigt værktøj og ikke en
    # Streamlit-demo. Se CLAUDE.md: "Rapportens udseende".
    #
    # OBS 1: st.markdown's HTML-blok-genkendelse (CommonMark) afbrydes af
    # den FØRSTE tomme linje i en blok der ikke starter med <style>/<script>
    # -- derfor INGEN tomme linjer inde i denne blok.
    # OBS 2: en <link rel="stylesheet"> indsat via unsafe_allow_html bliver
    # aldrig hentet (Streamlit renderer det midt i <body>, ikke i <head>,
    # og React's dangerouslySetInnerHTML udløser ikke ressource-hentning for
    # den slags injicerede tags). @import inde i selve <style>-blokken
    # virker derimod, fordi <style>-tagget allerede er bekræftet virkende
    # (resten af reglerne herunder anvendes jo).
    st.markdown(
        """<style>
        @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap');
        .wrap, .wrap *{font-family:Archivo,system-ui,sans-serif!important}
        header[data-testid="stHeader"]{display:none}
        .block-container{padding-top:2.5rem;padding-bottom:3rem}
        /* sidebar: match rapportens mørke tema i stedet for Streamlits graa standard */
        [data-testid="stSidebar"]{background:var(--panel);border-right:1px solid var(--rule)}
        [data-testid="stSidebar"] > div{padding-top:1.5rem}
        [data-testid="stSidebar"] h3{font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);margin:0 0 18px}
        [data-testid="stSidebar"] label p{font-size:12.5px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--dim)}
        [data-testid="stSidebar"] [data-baseweb="select"] > div{background:var(--bg)!important;border-color:var(--rule)!important;border-radius:2px!important}
        [data-testid="stSidebar"] [data-baseweb="select"]:hover > div{border-color:var(--hot)!important}
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:var(--dim)}
        [data-testid="stSidebar"] hr{border-color:var(--rule)}
        /* download-knap: matcher rapportens outline-stil i stedet for Streamlits standardknap */
        .stDownloadButton button{background:transparent!important;color:var(--hot)!important;border:1px solid var(--hot)!important;border-radius:2px!important;font-weight:600!important}
        .stDownloadButton button:hover{background:var(--hot)!important;color:#171112!important}
        </style>""",
        unsafe_allow_html=True,
    )

    kampe = laes_manifest()

    with st.sidebar:
        st.markdown("### Vælg modstander")
        if not kampe:
            st.warning("Intet manifest fundet endnu (manifest.jsonl). Kør downloaderen først:\n\n`python downloader/hent_demoer.py`")
            st.stop()

        ligaer = sorted({k.liga for k in kampe})
        liga = st.selectbox("Liga", ligaer)

        hold_liste = hold_i_liga(kampe, liga)
        hold = st.selectbox("Modstander", hold_liste)

        maps = maps_for_hold(kampe, liga, hold)
        if not maps:
            st.info("Ingen kendte maps for dette hold endnu.")
            st.stop()
        map_navn = st.selectbox("Map", maps)

        st.caption(f"Genereret {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    veto = laes_veto()
    vis_rapport(kampe, veto, liga, hold, map_navn)


if __name__ == "__main__":
    main()
