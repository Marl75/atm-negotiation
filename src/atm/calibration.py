"""Turnaround calibrated on the data, and the model comparison behind it (`atm calibrate`).

Fit on January-June 2015, tested on July-December (temporal split), only on rows whose inbound delay comes from the
previous leg (no LATE_AIRCRAFT_DELAY leak). The turnaround is the median time between the inbound landing and our
actual departure, on departures constrained by the inbound (LATE_AIRCRAFT_DELAY > 0).

Result frozen below (`atm calibrate` recomputes it): per-airline turnaround cuts the departure-delay error on the
test months from 16.7 to 14.0 min and its bias from -12.2 to -7.6 min. Statistical residual layers (M2, M3) were
measured and not adopted: small gains for a less explainable model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Median observed turnaround (min) when the departure waits for the inbound, Jan-Jun 2015, from flights.csv
TURNAROUND_BY_AIRLINE = {"AA": 49, "AS": 42, "B6": 46, "DL": 48, "EV": 33, "F9": 42, "HA": 27, "MQ": 34,
                         "NK": 47, "OO": 30, "UA": 54, "US": 47, "VX": 47, "WN": 37}
DEFAULT_TURNAROUND_MIN = 40  # all-airline median, for an airline not in the table
TRAIN_MONTHS, TEST_MONTHS = range(1, 7), range(7, 13)
SOURCE = "median observed turnaround of the airline when waiting for the inbound, Jan-Jun 2015 (calibration.py)"


def turnaround_min(airline: str) -> int:
    return TURNAROUND_BY_AIRLINE.get(airline, DEFAULT_TURNAROUND_MIN)


def inbound_legs(f: pd.DataFrame) -> pd.DataFrame:
    """Rows with their previous leg (same tail, same day, landed at our origin before our departure)."""
    day = ["TAIL_NUMBER", "YEAR", "MONTH", "DAY"]
    left = f.reset_index()[["index", *day, "ORIGIN_AIRPORT", "DEP_MIN"]]
    prev = f[[*day, "DESTINATION_AIRPORT", "ARR_MIN", "ARRIVAL_DELAY"]].rename(
        columns={"DESTINATION_AIRPORT": "ORIGIN_AIRPORT", "ARR_MIN": "P_ARR", "ARRIVAL_DELAY": "P_DELAY"})
    m = left.merge(prev, on=[*day, "ORIGIN_AIRPORT"])
    m = m[m["P_ARR"] < m["DEP_MIN"]].sort_values("P_ARR").groupby("index").tail(1).set_index("index")
    d = f.join(m[["P_ARR", "P_DELAY"]], how="inner")
    d["IN_LANDED"] = d["P_ARR"] + d["P_DELAY"]
    d["TURN_OBS"] = d["DEP_MIN"] + d["DEPARTURE_DELAY"] - d["IN_LANDED"]
    d["HOUR"] = d["DEP_MIN"] // 60
    return d


def fit_turnaround(train: pd.DataFrame, q: float = 0.5) -> pd.Series:
    return train[train["LATE_AIRCRAFT_DELAY"] > 0].groupby("AIRLINE")["TURN_OBS"].quantile(q)


def compare_models(f: pd.DataFrame) -> pd.DataFrame:
    """M0 fixed 35 min | M1 per-airline turnaround | M2 + residual departure delay | M3 + arrival-side median."""
    d = inbound_legs(f)
    tr, te = d[d["MONTH"].isin(TRAIN_MONTHS)], d[d["MONTH"].isin(TEST_MONTHS)]
    dep = lambda df, turn: (df["IN_LANDED"] + turn - df["DEP_MIN"]).clip(lower=0)
    turn = fit_turnaround(tr)
    p0 = dep(te, 35)
    p1 = dep(te, te["AIRLINE"].map(turn).fillna(DEFAULT_TURNAROUND_MIN))

    r = tr["DEPARTURE_DELAY"] - dep(tr, tr["AIRLINE"].map(turn).fillna(DEFAULT_TURNAROUND_MIN))
    g = r.groupby([tr["AIRLINE"], tr["ORIGIN_AIRPORT"], tr["HOUR"]]).agg(["median", "count"])
    base = r.groupby(tr["AIRLINE"]).median()
    key = pd.MultiIndex.from_frame(te[["AIRLINE", "ORIGIN_AIRPORT", "HOUR"]])
    med, n = g["median"].reindex(key).to_numpy(), g["count"].reindex(key).fillna(0).to_numpy()
    b = te["AIRLINE"].map(base).fillna(0).to_numpy()
    p2 = p1 + (n * np.where(np.isnan(med), b, med) + 20 * b) / (n + 20)  # shrunk to the airline median
    arr = (tr["ARRIVAL_DELAY"] - tr["DEPARTURE_DELAY"]).groupby([tr["AIRLINE"], tr["DESTINATION_AIRPORT"]]).median()
    akey = pd.MultiIndex.from_frame(te[["AIRLINE", "DESTINATION_AIRPORT"]])
    p3 = p2 + arr.reindex(akey).fillna(-3).to_numpy()

    rows = []
    for name, pd_, pa in (("M0 fixed 35 min turnaround", p0, p0), ("M1 per-airline turnaround (adopted)", p1, p1),
                          ("M2 M1 + residual airline x origin x hour", p2, p2), ("M3 M2 + arrival-side median", p2, p3)):
        ed, ea = pd_ - te["DEPARTURE_DELAY"], pa - te["ARRIVAL_DELAY"]
        rows.append(dict(model=name, test_rows=len(te), dep_MAE=round(ed.abs().mean(), 1), dep_bias=round(ed.mean(), 1),
                         arr_MAE=round(ea.abs().mean(), 1), arr_bias=round(ea.mean(), 1),
                         arr_within_15min_pct=round(100 * (ea.abs() <= 15).mean(), 1)))
    return pd.DataFrame(rows)
