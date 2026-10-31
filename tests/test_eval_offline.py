"""Eval pipeline with fake agents (no API call). Needs data/raw/flights.csv."""

import pandas as pd
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


def test_dot_cause_minutes_reach_agents_but_not_the_rules():
    from atm.agents import ATCAgent, GroundAgent, PilotAgent
    from atm.constraints import check_all
    from atm.data import build_scenario, disruptions
    from atm.negotiation import naive_initial

    r = disruptions(FLIGHTS).iloc[356]
    s, c = build_scenario(FLIGHTS, r)
    assert s.dot_delay_causes_min.late_aircraft == r["LATE_AIRCRAFT_DELAY"]
    # Agents see them (brief: pass the row parameters to the 3 agents)
    for a in (ATCAgent(), PilotAgent(), GroundAgent()):
        assert '"dot_delay_causes_min"' in a.prompt(s, c, naive_initial(s, c))
    # Rules don't: inflate the minutes, nothing deterministic moves
    s2 = s.model_copy(update={"dot_delay_causes_min": s.dot_delay_causes_min.model_copy(
        update={"weather": 999, "late_aircraft": 999, "air_system": 999, "airline": 999, "security": 999})})
    assert naive_initial(s2, c) == naive_initial(s, c)
    assert deterministic_resolution(s2, c) == deterministic_resolution(s, c)
    p = naive_initial(s, c)
    assert [x.passed for x in check_all(s2, c, p)] == [x.passed for x in check_all(s, c, p)]
    # Columns the context never reads: changing them leaves the context identical
    r2 = r.copy()
    r2[["AIR_SYSTEM_DELAY", "AIRLINE_DELAY", "SECURITY_DELAY"]] = 999
    assert build_scenario(FLIGHTS, r2)[1] == c


def test_populations_are_disjoint_and_filtered():
    from atm.evaluate import populations

    s = populations(FLIGHTS, "prev_leg", n=10, samples=3)
    ids = [set(x.index) for x in s]
    assert all(len(x) == 10 for x in s) and not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    assert all(x["KNOWN_DELAY_SRC"].str.startswith("previous leg").all() for x in s)


def test_stress_population_only_has_problem_flights():
    from atm.audit import screen
    from atm.evaluate import populations

    (rows,) = populations(FLIGHTS, "stress", n=5, samples=1, workers=1, pool_size=200)
    res = screen(rows, workers=1, flights=FLIGHTS)
    assert ((res["sq_hard_fails"] != "") | (res["sq_holding"] > 0)).all()


def test_budget_cap_stops_api_calls():
    df, summary, _ = run_eval(FLIGHTS, n=4, agents=[Fixer(r) for r in Role], workers=1, max_cost_usd=0)
    assert (df["error"] == "budget cap reached, not run").all() and summary["llm_calls"] == 0


def test_report_reads_empty_failures_back_from_csv(tmp_path):
    from atm.evaluate import aggregate

    df, summary, out = run_eval(FLIGHTS, n=6, agents=[RubberStamp(r) for r in Role], workers=1)
    report = aggregate([out])
    assert f"| status_quo_unsafe | {summary['status_quo_unsafe']} |" in report


def test_summary_survives_budget_capped_rows():
    from atm.evaluate import summarize

    df, summary, _ = run_eval(FLIGHTS, n=4, agents=[Fixer(r) for r in Role], workers=1)
    mixed = pd.concat([df, pd.DataFrame([{"flight_id": "X1", "error": "budget cap reached, not run"}])],
                      ignore_index=True)
    s = summarize(mixed)  # crashed with "None of [Index([-1, -2, ...])]" before the bool fix
    assert s["errors"] == 1 and s["final_solutions_safe_when_solvable"] == summary["final_solutions_safe_when_solvable"]


def test_outcome_rebuilt_from_log_gives_same_metrics(tmp_path):
    import glob
    from atm import negotiation
    from atm.data import disruptions
    from atm.evaluate import outcome_from_log, run_case

    r = disruptions(FLIGHTS).iloc[356]
    live = run_case(FLIGHTS, r, agents=[Fixer(x) for x in Role])
    log = max(glob.glob(str(negotiation.LOG_DIR / "*.jsonl")))
    rebuilt = run_case(FLIGHTS, r, outcome=outcome_from_log(log))
    live.pop("latency_s"); rebuilt.pop("latency_s")
    assert rebuilt == live


def test_first_sample_is_stable_across_sample_counts():
    from atm.evaluate import populations

    one = populations(FLIGHTS, "prev_leg", n=10, samples=1)[0]
    three = populations(FLIGHTS, "prev_leg", n=10, samples=3)
    assert list(one.index) == list(three[0].index) and not set(one.index) & set(three[1].index)
