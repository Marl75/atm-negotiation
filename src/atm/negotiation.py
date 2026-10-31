"""Orchestrator: bounded rounds, hard checks after every proposal, traceable consensus log."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .agents import ATCAgent, GroundAgent, PilotAgent
from .config import LOG_DIR, MAX_ROUNDS
from .constraints import check_all, hard_ok
from .fallback import deterministic_resolution, min_gap
from .protocol import LEVERS, Disruption, Evaluation, HumanDecision, OpsContext, Outcome, Proposal, Role, Turn


def naive_initial(s: Disruption, context: OpsContext) -> Proposal:
    """Status quo without coordination, also ATC's first offer: the aircraft departs as soon as it is ready, gets the
    first-come-first-served slot, waits for it in airborne holding, keeps its planned gate. Separation is respected."""
    runway = min(context.runway_slots, key=lambda r: context.runway_slots[r].earliest_delay_min)
    slot = context.runway_slots[runway].earliest_delay_min
    return Proposal(revised_arrival_delay_min=slot, holding_min=max(0, slot - context.ready_arrival_delay_min),
                    slot_gap_min=min_gap(context, runway), runway=runway, gate=context.planned_gate,
                    rationale="status quo: depart when ready, absorb the arrival queue in airborne holding")


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
            upgrade = ground_hold_upgrade(scenario, context, proposal)
            if upgrade and rnd < MAX_ROUNDS:  # agreed plan still flies holding: put the ground hold to a vote
                proposal, proposer, turns[-1].next_selection = upgrade
                continue
            if upgrade:
                turns[-1].next_selection = "ground-hold variant better but no round left: consensus kept"
            return _finish(Outcome(scenario=scenario, context=context, turns=turns, consensus=True,
                                   final=proposal, resolved_by="consensus"))

        picked = select_counter(scenario, context, evaluations, current=proposal)
        if picked is None:
            reason = f"turn {rnd}: agents rejected without any counter-proposal"
            break
        proposal, proposer, turns[-1].next_selection = picked
    else:
        reason = f"no consensus after {MAX_ROUNDS} turns"

    last = turns[-1]
    objectors = [f"{e.role.value} ({', '.join(e.violated_constraints) or 'no constraint cited'})"
                 for e in last.evaluations if not e.accept]
    failed = [c.constraint for c in last.hard_checks if c.hard and not c.passed]
    reason += (f"; last proposal rejected by {', '.join(objectors) or 'nobody'}"
               + (f", failing hard checks {', '.join(failed)}" if failed else ""))
    final = deterministic_resolution(scenario, context)
    reason += ("; deterministic solver chose the earliest plan passing every hard check" if final else
               "; no plan passes every hard check: escalated to the approach supervisor")
    return _finish(Outcome(scenario=scenario, context=context, turns=turns, consensus=False, final=final,
                           resolved_by="deterministic_fallback", fallback_reason=reason))


def score(scenario: Disruption, context: OpsContext, p: Proposal) -> tuple[int, int, int, int]:
    """Lower is better, compared in order: safety first, then cost.

    1. hard (safety) failures   2. soft (cost) failures
    3. airborne holding minutes (~4-5x the cost of a ground minute, EUROCONTROL)   4. total delay
    """
    checks = check_all(scenario, context, p)
    return (sum(not c.passed for c in checks if c.hard), sum(not c.passed for c in checks if not c.hard),
            p.holding_min, p.revised_arrival_delay_min)


def ground_hold_upgrade(scenario: Disruption, context: OpsContext,
                        agreed: Proposal) -> tuple[Proposal, str, str] | None:
    """A consensus that still flies airborne holding: same plan with the holding moved to a ground hold at origin,
    if the rules score it strictly better. Deterministic, so it does not depend on an agent thinking of it (AA204)."""
    if agreed.holding_min == 0:
        return None
    variant = agreed.model_copy(update={
        "holding_min": 0,
        "rationale": f"{agreed.rationale} | {agreed.holding_min} min airborne holding moved to a ground hold at origin"})
    before, after = score(scenario, context, agreed), score(scenario, context, variant)
    if after >= before:
        return None
    return variant, "GROUND_HOLD<consensus", f"consensus {before} upgraded to ground hold {after}, put to a vote"


def merge_counters(current: Proposal, evaluations: list[Evaluation]) -> Proposal | None:
    """Combine counter-proposals: each role's changes are taken only on its own levers (LEVERS are disjoint)."""
    changes, notes = {}, []
    for e in evaluations:
        if not e.counter_proposal:
            continue
        own = {f: getattr(e.counter_proposal, f) for f in LEVERS[e.role]
               if getattr(e.counter_proposal, f) != getattr(current, f)}
        if own:
            changes |= own
            notes.append(f"{e.role.value}: " + ", ".join(f"{f}={v}" for f, v in own.items()))
    if len(notes) < 2:  # nothing to combine: same as a single counter
        return None
    return current.model_copy(update=changes | {"rationale": "merged counters - " + "; ".join(notes)})


def select_counter(scenario: Disruption, context: OpsContext, evaluations: list[Evaluation],
                   current: Proposal | None = None) -> tuple[Proposal, Role | str, str] | None:
    """Deterministic pick among all agents' counter-proposals and their merge (not the LLM's call), with a logged reason.

    Two non-LLM candidates are also scored, listed last so an agent proposal wins any tie:
    - GROUND_HOLD: each candidate with airborne holding moved to a ground hold at origin (same arrival time).
      Assumes the delay is known before departure, as in an FAA Ground Delay Program.
    - SOLVER: the deterministic resolution.
    """
    candidates = [(e.role, e.counter_proposal) for e in evaluations if e.counter_proposal]
    if not candidates:
        return None  # nobody proposes anything: stop negotiating, the fallback decides
    merged = merge_counters(current, evaluations) if current else None
    if merged:
        candidates.append(("MERGED", merged))
    candidates += [(f"GROUND_HOLD<{getattr(who, 'value', who)}", p.model_copy(update={
                       "holding_min": 0,
                       "rationale": f"{p.rationale} | {p.holding_min} min airborne holding moved to a ground hold at origin"}))
                   for who, p in list(candidates) if p.holding_min > 0]
    solver = deterministic_resolution(scenario, context)
    if solver:
        candidates.append(("SOLVER", solver))
    ranked = sorted(((score(scenario, context, p), i, who, p) for i, (who, p) in enumerate(candidates)),
                    key=lambda x: (x[0], x[1]))
    if not ranked:
        return None
    best_score, _, who, best = ranked[0]
    name = lambda r: getattr(r, "value", r)
    reason = " | ".join(f"{name(w)} (hard_fail, soft_fail, holding, delay)={s}" for s, _, w, _ in ranked)
    return best, who, f"picked {name(who)} {best_score}; candidates: {reason}"


def _finish(outcome: Outcome) -> Outcome:
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = LOG_DIR / f"{outcome.scenario.flight_id}_{stamp}.jsonl"
    path.write_text(
        "\n".join(t.model_dump_json() for t in outcome.turns) + "\n" + outcome.model_dump_json(exclude={"turns"})
    )
    outcome._log_path = str(path)
    return outcome


def record_decision(outcome: Outcome, decision: HumanDecision) -> Outcome:
    """Attach the supervisor's decision and rewrite the log's last line (the outcome), so the log stays one file
    with the same shape: turns, then the outcome, now with `human_decision` filled."""
    outcome.human_decision = decision
    if outcome._log_path:
        path = Path(outcome._log_path)
        lines = path.read_text().splitlines()
        lines[-1] = outcome.model_dump_json(exclude={"turns"})
        path.write_text("\n".join(lines) + "\n")
    return outcome
