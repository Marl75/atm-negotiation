"""Calibration (no API call). Needs data/raw/flights.csv."""

import pytest

from atm.calibration import (TRAIN_MONTHS, TURNAROUND_BY_AIRLINE, compare_models, fit_turnaround, inbound_legs,
                             turnaround_min)
from atm.data import flights_path, load_flights

try:
    flights_path()
except FileNotFoundError:
    pytest.skip("flights.csv not available", allow_module_level=True)

FLIGHTS = load_flights()


def test_frozen_turnaround_matches_a_fresh_fit():
    d = inbound_legs(FLIGHTS)
    fit = fit_turnaround(d[d["MONTH"].isin(TRAIN_MONTHS)]).round().astype(int).to_dict()
    assert fit == TURNAROUND_BY_AIRLINE


def test_adopted_model_beats_fixed_turnaround_on_test_months():
    r = compare_models(FLIGHTS).set_index("model")
    m0, m1 = r.iloc[0], r.loc["M1 per-airline turnaround (adopted)"]
    assert m1["dep_MAE"] < m0["dep_MAE"] and abs(m1["dep_bias"]) < abs(m0["dep_bias"])


def test_unknown_airline_gets_default():
    assert turnaround_min("ZZ") == 40 and turnaround_min("UA") == 54
