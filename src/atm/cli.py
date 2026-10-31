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
    from .data import build_scenario, disruptions, load_flights
    from .negotiation import naive_initial, negotiate

    flights = load_flights()
    s, c = build_scenario(flights, disruptions(flights).iloc[row])
    out = negotiate(s, c, naive_initial(s, c))
    print(out.model_dump(exclude={"turns"}))


def evaluate(n: int, seed: int, workers: int) -> None:
    from .data import load_flights
    from .evaluate import run_eval

    _, summary, out = run_eval(load_flights(), n, seed, workers)
    print(summary)
    print(f"-> {out}")


def audit(n: int, seed: int, workers: int, gates: int, planned_gate: str) -> None:
    from .audit import run_audit

    _, summary, out = run_audit(n, seed, workers, gates, planned_gate)
    print(summary)
    print(f"-> {out}")


def calibrate() -> None:
    from .calibration import TRAIN_MONTHS, compare_models, fit_turnaround, inbound_legs
    from .data import load_flights

    f = load_flights()
    print(compare_models(f).to_string(index=False))
    d = inbound_legs(f)
    turn = fit_turnaround(d[d["MONTH"].isin(TRAIN_MONTHS)]).round().astype(int).to_dict()
    print(f"\nturnaround per airline (Jan-Jun fit): {turn}")


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
    a = sub.add_parser("audit", help="status quo vs rules on many flights, no LLM")
    a.add_argument("--n", type=int, default=10_000)
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--workers", type=int, default=8)
    a.add_argument("--gates", type=int, default=4, help="gates per airline at destination (assumption)")
    a.add_argument("--planned-gate", choices=["first", "random"], default="first")
    sub.add_parser("calibrate", help="refit the turnaround and compare prediction models (temporal split, no LLM)")
    args = ap.parse_args()
    if args.cmd == "calibrate":
        calibrate()
    elif args.cmd == "check":
        check()
    elif args.cmd == "run":
        run(args.row)
    elif args.cmd == "audit":
        audit(args.n, args.seed, args.workers, args.gates, args.planned_gate)
    else:
        evaluate(args.n, args.seed, args.workers)
