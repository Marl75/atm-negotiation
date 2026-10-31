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
    unsafe_status_quo = int((df["status_quo_hard_fails"] != "").sum())
    assert summary["errors"] == 0
    # Agents accept everything: consensus only where the status quo is already safe, the checker refuses the rest
    assert int(df["consensus"].sum()) == 6 - unsafe_status_quo
    assert summary["agent_unsafe_accepts_caught"] == 3 * unsafe_status_quo
    solved = df[~df["escalated"]]
    assert solved["final_hard_ok"].all()


def test_fixer_agents_reach_consensus_in_two_rounds():
    df, summary, _ = run_eval(FLIGHTS, n=6, agents=[Fixer(r) for r in Role], workers=1)
    solved = df[~df["escalated"]]
    assert solved["consensus"].all() and (solved["rounds"] == 2).all()
    assert solved["final_hard_ok"].all() and summary["mean_holding_negotiated"] == 0


def test_final_author_and_source_split():
    df, summary, _ = run_eval(FLIGHTS, n=6, agents=[Fixer(r) for r in Role], workers=1)
    solved = df[~df["escalated"]]
    # Fixers all counter with the solver's proposal: on a tie the first agent (ATC) wins, never SOLVER
    assert (solved["final_author"] == "ATC").all()
    assert set(summary["slot_model_MAE_vs_real_arrival_min"]) == {"prev_leg", "proxy_LATE_AIRCRAFT_DELAY_leaky"}
    split = summary["slot_model_MAE_vs_real_arrival_min"]
    assert split["prev_leg"]["n"] + split["proxy_LATE_AIRCRAFT_DELAY_leaky"]["n"] == 6
