"""Rules-only audit (no API call). Needs data/raw/flights.csv."""

import pytest

from atm import context as ctx_mod
from atm.audit import run_audit, wilson
from atm.data import flights_path, load_flights

try:
    flights_path()
except FileNotFoundError:
    pytest.skip("flights.csv not available", allow_module_level=True)

FLIGHTS = load_flights()


def test_wilson_interval():
    lo, hi = wilson(20, 100)
    assert lo < 20 < hi and wilson(0, 0) == (0.0, 0.0)


def test_audit_runs_and_restores_gate_assumption():
    df, summary, _ = run_audit(n=30, workers=1, gates_per_airline=8, planned_gate="random", flights=FLIGHTS)
    assert summary["flights"] == 30 and summary["status_quo_unsafe"]["n"] == 30
    assert ctx_mod.GATES_PER_AIRLINE is None  # sensitivity value does not leak into the model


def test_solver_never_worse_than_status_quo_on_holding():
    df, _, _ = run_audit(n=30, workers=1, flights=FLIGHTS)
    ok = df.dropna(subset=["fb_holding"])
    assert (ok["fb_holding"] <= ok["sq_holding"]).all()
