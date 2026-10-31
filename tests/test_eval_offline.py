"""Eval pipeline with fake agents (no API call). Needs data/raw/flights.csv."""

import pytest

from atm.data import flights_path, load_flights
from atm.evaluate import run_eval
from atm.fallback import deterministic_resolution
from atm.protocol import Evaluation, Role

try:
    flights_path()
except FileNotFoundError:
    pytest.skip("flights.csv not available", allow_module_level=True)

FLIGHTS = load_flights()


class RubberStamp:
    """Accepts anything: the checker must refuse its unsafe consensus."""
    def __init__(self, role): self.role = role
    def evaluate(self, s, c, p, history=""): return Evaluation(role=self.role, accept=True)


class Fixer:
    """Rejects round 1 with the deterministic solution as counter, then accepts."""
    def __init__(self, role): self.role = role
    def evaluate(self, s, c, p, history=""):
        if history:
            return Evaluation(role=self.role, accept=True)
        return Evaluation(role=self.role, accept=False, counter_proposal=deterministic_resolution(s, c))


def test_rubber_stamp_agents_are_overruled():
    df, summary, _ = run_eval(FLIGHTS, n=6, agents=[RubberStamp(r) for r in Role], workers=1)
    assert summary["errors"] == 0 and summary["consensus_rate"] == 0
    assert summary["fallback_rate"] == 1 and summary["final_solutions_safe"] == "6/6"
    assert summary["agent_unsafe_accepts_caught"] == 18  # 3 agents x 6 cases


def test_fixer_agents_reach_consensus_in_two_rounds():
    df, summary, _ = run_eval(FLIGHTS, n=6, agents=[Fixer(r) for r in Role], workers=1)
    assert summary["consensus_rate"] == 1 and summary["mean_rounds"] == 2
    assert summary["final_solutions_safe"] == "6/6" and summary["mean_holding_negotiated"] == 0
