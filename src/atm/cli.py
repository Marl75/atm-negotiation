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
    from .negotiation import naive_initial, negotiate

    flights = load_flights()
    r = disruptions(flights).iloc[row]
    s = row_to_disruption(r)
    c = build_context(s, next_departure_same_tail(flights, r))
    out = negotiate(s, c, naive_initial(c))
    print(out.model_dump(exclude={"turns"}))


def evaluate(n: int, seed: int, workers: int) -> None:
    from .data import load_flights
    from .evaluate import run_eval

    _, summary, out = run_eval(load_flights(), n, seed, workers)
    print(summary)
    print(f"-> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="atm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--row", type=int, default=0)
    e = sub.add_parser("eval")
    e.add_argument("--n", type=int, default=20)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.cmd == "check":
        check()
    elif args.cmd == "run":
        run(args.row)
    else:
        evaluate(args.n, args.seed, args.workers)
