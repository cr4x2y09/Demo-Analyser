#!/usr/bin/env python3
"""
Trin 1: Find en modstanders default-opstillinger.

Brug:
    python defaults.py demos/ "MASQ" --side T --sekunder 20

Forudsaetninger:
    pip install awpy matplotlib
    awpy get maps      # radarbilleder
    awpy get tris      # noedvendig for plot()
"""

import argparse
from collections import Counter
from pathlib import Path

import polars as pl
from awpy import Demo


# CS2 GOTV-demoer koerer normalt 64 tick. awpy defaulter til 128,
# saa hvis du ikke saetter det her, bliver alle dine tidsberegninger
# dobbelt saa lange som de skal vaere. Klassisk faelde.
TICKRATE = 64


def snapshots_fra_demo(sti: Path, holdnavn: str, side: str, sekunder: int) -> pl.DataFrame:
    """Parser en demo og returnerer spillerpositioner N sekunder inde i hver runde."""
    dem = Demo(sti, tickrate=TICKRATE)
    # awpy 2.0.2 omdoeber "team_name" til "side" (kun t/ct) internt -- det
    # rigtige holdnavn ("MASQ" osv.) skal bedes om eksplicit som
    # "team_clan_name", ellers findes det slet ikke som kolonne i dem.ticks.
    # Verificeret mod en rigtig demo 2026-09-02.
    dem.parse(player_props=["team_clan_name"])

    kort = dem.header.get("map_name", "ukendt")
    offset = sekunder * TICKRATE

    # Ticket vi vil kigge paa: N sekunder efter freezetime slutter.
    maal = dem.rounds.select(
        pl.col("round_num"),
        (pl.col("freeze_end") + offset).alias("snapshot_tick"),
        pl.col("end").alias("slut_tick"),
    ).filter(
        # Drop runder der sluttede foer vores snapshot -- typisk hurtige
        # eco-runder. De forurener billedet af hvad et "default" er.
        pl.col("snapshot_tick") < pl.col("slut_tick")
    )

    rows = []
    for r in maal.iter_rows(named=True):
        frame = dem.ticks.filter(
            (pl.col("tick") == r["snapshot_tick"])
            & (pl.col("team_clan_name") == holdnavn)
            & (pl.col("side") == side)
            & (pl.col("health") > 0)          # doede spillere staar ikke i default
        )
        if frame.height:
            rows.append(frame.with_columns(
                kamp=pl.lit(sti.name),
                kort=pl.lit(kort),
            ))

    if not rows:
        return pl.DataFrame()
    return pl.concat(rows, how="diagonal")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mappe", type=Path, help="mappe med .dem-filer")
    ap.add_argument("hold", help="holdnavn praecis som det staar i demoen")
    ap.add_argument("--side", default="t", choices=["t", "ct"])
    ap.add_argument("--sekunder", type=int, default=20)
    ap.add_argument("--kort", default=None, help="filtrer paa ét kort, fx de_nuke")
    args = ap.parse_args()

    demoer = sorted(args.mappe.glob("*.dem"))
    if not demoer:
        raise SystemExit(f"Ingen .dem-filer i {args.mappe}")

    alle = []
    for d in demoer:
        print(f"parser {d.name} ...", flush=True)
        try:
            snap = snapshots_fra_demo(d, args.hold, args.side, args.sekunder)
        except Exception as e:                      # noqa: BLE001
            print(f"  sprunget over: {e}")
            continue
        if snap.height:
            alle.append(snap)
        else:
            print(f"  ingen runder matchede hold={args.hold!r} side={args.side!r}")

    if not alle:
        raise SystemExit(
            "Intet data. Tjek holdnavnet -- kor med --debug-navne hvis du er i tvivl."
        )

    df = pl.concat(alle, how="diagonal")
    if args.kort:
        df = df.filter(pl.col("kort") == args.kort)

    kort_navne = df["kort"].unique().to_list()
    print(f"\n{df.height} spiller-snapshots fra {len(demoer)} demoer paa {kort_navne}")

    # --- Det vigtigste output: hvor staar de, i callouts ---
    # Kolonnen hedder "place", ikke "last_place_name" -- awpy 2.0.2 omdoeber
    # den til det korte navn internt. Gratis og kraever ingen clustering.
    runder = df.select("kamp", "round_num").unique().height
    print(f"\nHyppigste positioner {args.sekunder}s inde i runden "
          f"({runder} runder, {args.side.upper()}-side):\n")

    taeller = Counter(df["place"].drop_nulls().to_list())
    for sted, antal in taeller.most_common(15):
        pct = 100 * antal / runder
        bar = "#" * int(pct / 4)
        print(f"  {sted:<20} {pct:5.1f}%  {bar}")

    # --- Radarplot ---
    if len(kort_navne) == 1:
        try:
            from awpy.plot import plot
            import matplotlib.pyplot as plt

            punkter = df.select("X", "Y", "Z").rows()
            fig, ax = plot(
                kort_navne[0],
                points=punkter,
                point_settings=[{"color": "#ff5c5c", "marker": "o", "size": 6}] * len(punkter),
            )
            ud = f"defaults_{args.hold}_{args.side}_{kort_navne[0]}.png"
            fig.savefig(ud, dpi=150, bbox_inches="tight")
            plt.close(fig)
            print(f"\nRadar gemt: {ud}")
        except Exception as e:                      # noqa: BLE001
            print(f"\nPlot sprang over ({e}). Kor 'awpy get maps' og 'awpy get tris'.")
    else:
        print("\nFlere kort i datasaettet -- brug --kort for at faa et radarplot.")


if __name__ == "__main__":
    main()
