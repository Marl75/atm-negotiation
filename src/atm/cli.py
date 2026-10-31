"""Entry point: `uv run atm check` (setup check), `uv run atm run --row N` (one negotiation, then the approach
supervisor approves or rejects), `uv run atm check-proposal` (deterministic checks of any proposal, as JSON)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from rich import print
from rich.markup import escape

from . import config
from .protocol import HumanDecision, Outcome


def check() -> None:
    print(f"model: {config.MODEL}  effort: {config.EFFORT}  max_rounds: {config.MAX_ROUNDS}")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    print(f"API key: {'OK' if key and key != 'sk-ant-...' else '[red]missing (.env)[/red]'}")
    try:
        from .data import flights_path, load_disruptions
        print(f"data: {flights_path()}  -> {len(load_disruptions(50_000))} disruption rows in first 50k")
    except FileNotFoundError as e:
        print(f"[yellow]data: {e}[/yellow]")


def summary(out: Outcome) -> str:
    """What the supervisor reads before deciding: the plan, every check of that plan, each agent's last word."""
    from .constraints import check_all

    s, f = out.scenario, out.final
    lines = [f"[bold]{escape(s.flight_id)}[/bold] {s.origin} -> {s.destination}, sched. arrival {s.scheduled_arrival}, "
             f"cause {s.cause}, resolved by {out.resolved_by} after {len(out.turns)} round(s)"]
    if f is None:
        lines += ["[bold red]ESCALATED: no safe option[/bold red] - the solver found no plan passing every hard "
                  "(safety) check. Nothing to approve: the supervisor must decide the handling."]
    else:
        ground = f.revised_arrival_delay_min - f.holding_min - out.context.ready_arrival_delay_min
        lines += ["", "[bold]Final plan[/bold]",
                  f"  delay +{f.revised_arrival_delay_min} min  (airborne holding {f.holding_min} min, "
                  f"ground hold at {s.origin} {ground} min)",
                  f"  runway {f.runway}  gap {f.slot_gap_min} min  gate {f.gate}  reroute {f.reroute}",
                  f"  rationale: {escape(f.rationale)}", "", "[bold]Checks[/bold] (deterministic, on the final plan)"]
        for r in check_all(s, out.context, f):
            mark = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]" if r.hard else "[yellow]FAIL[/yellow]"
            lines.append(f"  {mark} {'hard' if r.hard else 'soft'} {r.role.value:6} {r.constraint}: {escape(r.detail)}")
            lines.append(f"       [dim]{r.basis.value} - {escape(r.source)}[/dim]")
    if out.turns:
        lines += ["", f"[bold]Agents[/bold] (round {out.turns[-1].round})"]
        for e in out.turns[-1].evaluations:
            lines.append(f"  {e.role.value:6} {'accepts' if e.accept else 'rejects'}"
                         + (f", violated: {escape(', '.join(e.violated_constraints))}" if e.violated_constraints else ""))
            lines += [f"         - {escape(c)}" for c in e.concerns] or ["         - no concerns"]
    return "\n".join(lines)


def decide(out: Outcome, auto_approve: bool = False, ask: Callable[[str], str] = input) -> HumanDecision:
    """The approach supervisor's decision. No silent None: a missing plan is recorded as an escalation."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if out.final is None:
        reason = "no safe option, handed to the supervisor (auto)" if auto_approve else \
            ask("No safe option. Supervisor, how will you handle this flight? ").strip() or "no reason given"
        return HumanDecision(decision="escalated", reason=f"escalated: no safe option - {reason}",
                             decided_at=now, auto=auto_approve)
    if auto_approve:
        return HumanDecision(decision="approved", reason="--auto-approve (non-interactive)", decided_at=now, auto=True)
    while (answer := ask("Approach supervisor, approve this plan? [a]pprove / [r]eject: ").strip().lower()) \
            not in ("a", "approve", "r", "reject"):
        pass
    reason = ask("Reason: ").strip() or "no reason given"
    return HumanDecision(decision="approved" if answer.startswith("a") else "rejected", reason=reason, decided_at=now)


def run(row: int, auto_approve: bool = False) -> None:
    from .data import build_scenario, disruptions, load_flights
    from .negotiation import naive_initial, negotiate, record_decision

    flights = load_flights()
    s, c = build_scenario(flights, disruptions(flights).iloc[row])
    out = negotiate(s, c, naive_initial(s, c))
    print(summary(out))
    print()
    d = record_decision(out, decide(out, auto_approve)).human_decision
    print(f"[bold]{d.decision.upper()}[/bold] by {d.decided_by} at {d.decided_at}: {escape(d.reason)}")
    print(f"-> {out._log_path}")


def check_proposal(row: int | None, log: str | None, overrides: dict) -> None:
    """Deterministic checks of a proposal as JSON on stdout. The scenario comes from a DOT row or a negotiation log
    (its last line); the proposal starts from the status quo and takes JSON from stdin, then flags, on top."""
    from .constraints import check_all, hard_ok
    from .negotiation import naive_initial
    from .protocol import Disruption, OpsContext, Proposal

    if log:
        last = json.loads([x for x in open(log).read().splitlines() if x.strip()][-1])
        s, c = Disruption(**last["scenario"]), OpsContext(**last["context"])
    else:
        from .data import build_scenario, disruptions, load_flights
        flights = load_flights()
        s, c = build_scenario(flights, disruptions(flights).iloc[row or 0])
    given = {} if sys.stdin.isatty() else json.loads(sys.stdin.read() or "{}")
    p = Proposal(**naive_initial(s, c).model_dump() | given | {k: v for k, v in overrides.items() if v is not None})
    checks = check_all(s, c, p)
    sys.stdout.write(json.dumps({"flight_id": s.flight_id, "proposal": p.model_dump(), "hard_ok": hard_ok(checks),
                                 "all_ok": all(r.passed for r in checks),
                                 "checks": [r.model_dump(mode="json") for r in checks]}, indent=2) + "\n")


def evaluate(n: int, seed: int, workers: int, population: str = "stratified", samples: int = 1,
             max_cost: float | None = None) -> None:
    from .data import load_flights
    from .evaluate import populations, run_eval

    flights = load_flights()
    if population == "stratified" and samples == 1:  # historical default: same 20 flights for seed 0
        _, summary, out = run_eval(flights, n, seed, workers, max_cost_usd=max_cost)
        print(summary)
        print(f"-> {out}")
        return
    for i, rows in enumerate(populations(flights, population, n, samples, seed)):
        _, summary, out = run_eval(flights, n, seed, workers, rows=rows, tag=f"{population}_s{seed}-{i + 1}of{samples}",
                                   max_cost_usd=max_cost)
        print(f"[{population} sample {i + 1}/{samples}] cost {summary['cost_usd']} $ -> {out}")


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
    r.add_argument("--auto-approve", action="store_true", help="record an approval without asking (non-interactive)")
    k = sub.add_parser("check-proposal", help="deterministic checks of a proposal as JSON (proposal JSON on stdin "
                                              "and/or flags, unset fields = status quo), no LLM")
    src = k.add_mutually_exclusive_group()
    src.add_argument("--row", type=int, help="DOT disruption row (default 0)")
    src.add_argument("--log", help="take scenario and context from a negotiation log (logs/*.jsonl), no CSV load")
    k.add_argument("--delay", dest="revised_arrival_delay_min", type=int)
    k.add_argument("--holding", dest="holding_min", type=int)
    k.add_argument("--gap", dest="slot_gap_min", type=float)
    k.add_argument("--runway")
    k.add_argument("--gate")
    k.add_argument("--rationale")
    e = sub.add_parser("eval")
    e.add_argument("--n", type=int, default=20)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--population", choices=["stratified", "prev_leg", "stress"], default="stratified",
                   help="prev_leg: no LATE_AIRCRAFT_DELAY leak; stress: status quo unsafe or holding (rules screen)")
    e.add_argument("--samples", type=int, default=1, help="disjoint samples of --n flights, run one after another")
    e.add_argument("--max-cost", type=float, help="USD cap per sample; flights beyond it are not run")
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
        run(args.row, args.auto_approve)
    elif args.cmd == "check-proposal":
        check_proposal(args.row, args.log, {f: getattr(args, f) for f in (
            "revised_arrival_delay_min", "holding_min", "slot_gap_min", "runway", "gate", "rationale")})
    elif args.cmd == "audit":
        audit(args.n, args.seed, args.workers, args.gates, args.planned_gate)
    else:
        evaluate(args.n, args.seed, args.workers, args.population, args.samples, args.max_cost)
