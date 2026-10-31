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
    from .context import build_context
    from .data import disruptions, load_flights, next_departure_same_tail, row_to_disruption
    from .negotiation import negotiate
    from .protocol import Proposal

    flights = load_flights()
    r = disruptions(flights).iloc[row]
    s = row_to_disruption(r)
    c = build_context(s, next_departure_same_tail(flights, r))
    # Naive first ATC offer (first runway / gate, short gap): may break constraints on purpose
    initial = Proposal(revised_arrival_delay_min=c.earliest_arrival_delay_min, holding_min=15, slot_gap_min=1.5,
                       runway=c.runways[0], gate=c.gates[0], rationale="initial ATC slot")
    out = negotiate(s, c, initial)
    print(out.model_dump(exclude={"turns"}))


def main() -> None:
    ap = argparse.ArgumentParser(prog="atm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--row", type=int, default=0)
    args = ap.parse_args()
    check() if args.cmd == "check" else run(args.row)
