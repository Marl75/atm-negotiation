"""Entry point: `uv run atm check` (setup check) or `uv run atm run --row N` (one negotiation)."""

from __future__ import annotations

import argparse
import os

from rich import print

from . import config


def check() -> None:
    print(f"model: {config.MODEL}  effort: {config.EFFORT}  max_rounds: {config.MAX_ROUNDS}")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    print(f"API key: {'OK' if key and key != 'sk-ant-...' else '[red]missing (.env)[/red]'}")
    try:
        from .data import flights_path, load_disruptions
        print(f"data: {flights_path()}  -> {len(load_disruptions(50_000))} disruption rows in first 50k")
    except FileNotFoundError as e:
        print(f"[yellow]data: {e}[/yellow]")


def run(row: int) -> None:
    from .data import load_disruptions, row_to_disruption
    from .negotiation import negotiate
    from .protocol import Proposal

    s = row_to_disruption(load_disruptions().iloc[row])
    initial = Proposal(revised_arrival_delay_min=int(s.weather_delay_min + s.late_aircraft_delay_min),
                       holding_min=15, runway="27L", gate="A1", rationale="initial ATC slot")
    out = negotiate(s, initial)
    print(out.model_dump(exclude={"turns"}))


def main() -> None:
    ap = argparse.ArgumentParser(prog="atm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--row", type=int, default=0)
    args = ap.parse_args()
    check() if args.cmd == "check" else run(args.row)
