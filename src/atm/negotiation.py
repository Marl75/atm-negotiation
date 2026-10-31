"""Orchestrator: bounded rounds, hard checks after every proposal, traceable consensus log."""

from __future__ import annotations

from datetime import datetime, timezone

from .agents import ATCAgent, GroundAgent, PilotAgent
from .config import LOG_DIR, MAX_ROUNDS
from .constraints import check_all, hard_ok
from .fallback import deterministic_resolution
from .protocol import Disruption, Evaluation, OpsContext, Outcome, Proposal, Role, Turn


def naive_initial(context: OpsContext) -> Proposal:
    """ATC's unilateral first offer (first runway / gate, short gap, no coordination). Also the status-quo baseline."""
    return Proposal(revised_arrival_delay_min=context.earliest_arrival_delay_min, holding_min=15, slot_gap_min=1.5,
                    runway=context.runways[0], gate=context.gates[0], rationale="initial ATC slot")


def negotiate(scenario: Disruption, context: OpsContext, initial: Proposal, agents: list | None = None) -> Outcome:
    agents = agents or [ATCAgent(), PilotAgent(), GroundAgent()]  # injectable for offline tests
    proposal, proposer, turns = initial, "ATC", []

    for rnd in range(1, MAX_ROUNDS + 1):
        history = "\n".join(t.model_dump_json() for t in turns)
        evaluations = [a.evaluate(scenario, context, proposal, history) for a in agents]
        checks = check_all(scenario, context, proposal)
        turns.append(Turn(round=rnd, proposal=proposal, proposed_by=proposer,
                          evaluations=evaluations, hard_checks=checks))

        # Consensus = every agent accepts AND no hard (safety) constraint fails. Soft failures are logged.
        if all(e.accept for e in evaluations) and hard_ok(checks):
            return _finish(Outcome(scenario=scenario, context=context, turns=turns, consensus=True,
                                   final=proposal, resolved_by="consensus"))

        picked = select_counter(scenario, context, evaluations)
        if picked is None:
            break
        proposal, proposer, turns[-1].next_selection = picked

    return _finish(Outcome(scenario=scenario, context=context, turns=turns, consensus=False,
                           final=deterministic_resolution(scenario, context), resolved_by="deterministic_fallback"))


def score(scenario: Disruption, context: OpsContext, p: Proposal) -> tuple[int, int, int, int]:
    """Lower is better, compared in order: safety first, then cost.

    1. hard (safety) failures   2. soft (cost) failures
    3. airborne holding minutes (~4-5x the cost of a ground minute, EUROCONTROL)   4. total delay
    """
    checks = check_all(scenario, context, p)
    return (sum(not c.passed for c in checks if c.hard), sum(not c.passed for c in checks if not c.hard),
            p.holding_min, p.revised_arrival_delay_min)


def select_counter(scenario: Disruption, context: OpsContext,
                   evaluations: list[Evaluation]) -> tuple[Proposal, Role, str] | None:
    """Deterministic pick among all agents' counter-proposals (not the LLM's call), with a logged reason."""
    ranked = sorted(((score(scenario, context, e.counter_proposal), i, e)
                     for i, e in enumerate(evaluations) if e.counter_proposal), key=lambda x: (x[0], x[1]))
    if not ranked:
        return None
    best_score, _, best = ranked[0]
    reason = " | ".join(f"{e.role.value} (hard_fail, soft_fail, holding, delay)={s}" for s, _, e in ranked)
    return best.counter_proposal, best.role, f"picked {best.role.value} {best_score}; candidates: {reason}"


def _finish(outcome: Outcome) -> Outcome:
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (LOG_DIR / f"{outcome.scenario.flight_id}_{stamp}.jsonl").write_text(
        "\n".join(t.model_dump_json() for t in outcome.turns) + "\n" + outcome.model_dump_json(exclude={"turns"})
    )
    return outcome
