"""Orchestrator: bounded rounds, hard checks after every proposal, traceable consensus log."""

from __future__ import annotations

from datetime import datetime, timezone

from .agents import ATCAgent, GroundAgent, PilotAgent
from .config import LOG_DIR, MAX_ROUNDS
from .constraints import check_all
from .fallback import deterministic_resolution
from .protocol import Disruption, Outcome, Proposal, Turn


def negotiate(scenario: Disruption, initial: Proposal) -> Outcome:
    agents = [ATCAgent(), PilotAgent(), GroundAgent()]
    proposal, proposer, turns = initial, "ATC", []

    for rnd in range(1, MAX_ROUNDS + 1):
        history = "\n".join(t.model_dump_json() for t in turns)
        evaluations = [a.evaluate(scenario, proposal, history) for a in agents]
        hard = check_all(scenario, proposal)
        turns.append(Turn(round=rnd, proposal=proposal, proposed_by=proposer,
                          evaluations=evaluations, hard_checks=hard))

        if all(e.accept for e in evaluations) and all(c.passed for c in hard):
            return _finish(Outcome(scenario=scenario, turns=turns, consensus=True,
                                   final=proposal, resolved_by="consensus"))

        # TODO: smarter counter-proposal selection (e.g. the one passing most hard checks)
        counter = next((e for e in evaluations if e.counter_proposal), None)
        if counter is None:
            break
        proposal, proposer = counter.counter_proposal, counter.role

    return _finish(Outcome(scenario=scenario, turns=turns, consensus=False,
                           final=deterministic_resolution(scenario), resolved_by="deterministic_fallback"))


def _finish(outcome: Outcome) -> Outcome:
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (LOG_DIR / f"{outcome.scenario.flight_id}_{stamp}.jsonl").write_text(
        "\n".join(t.model_dump_json() for t in outcome.turns) + "\n" + outcome.model_dump_json(exclude={"turns"})
    )
    return outcome
