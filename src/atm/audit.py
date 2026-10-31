"""Large-sample audit of the status quo, rules only (no LLM, no cost).

For each disrupted flight: would the uncoordinated plan (naive_initial) break a hard rule, how much airborne
holding would it fly, and can the deterministic solver find a safe plan? This measures the problem the agents
address on thousands of flights instead of the 20 of the LLM eval.

Sensitivity: the gate pool (workbook gates x airline share by default; context.GATES_PER_AIRLINE overrides) and
the planned gate (hash of the flight id by default) are assumptions.
`gates_per_airline` and `planned_gate="random"` re-run the audit under other values, to show how much of the
gate-conflict rate comes from those choices.
"""

from __future__ import annotations

import math
import random
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from . import context as ctx_mod
from .config import ROOT
from .constraints import check_all
from .data import build_scenario, disruptions, load_flights
from .rules import holding_burn_kg_per_min
from .fallback import deterministic_resolution
from .negotiation import naive_initial

AUDIT_DIR = ROOT / "eval" / "audit"
_FLIGHTS: pd.DataFrame | None = None


def _init(gates_per_airline: int | None) -> None:
    global _FLIGHTS
    ctx_mod.GATES_PER_AIRLINE = gates_per_airline  # per worker process, audit only
    _FLIGHTS = load_flights()


def audit_row(r: pd.Series, flights: pd.DataFrame, planned_gate: str = "first", seed: int = 0) -> dict:
    s, c = build_scenario(flights, r)
    if planned_gate == "random":
        own = [g for g in c.gates if not g.startswith("SPARE")]
        c = c.model_copy(update={"planned_gate": random.Random(f"{seed}{s.flight_id}").choice(own)})
    sq = naive_initial(s, c)
    checks = check_all(s, c, sq)
    fb = deterministic_resolution(s, c)
    return dict(flight_id=s.flight_id, cause=s.cause, destination=s.destination, airline=s.airline,
                wake_category=c.wake_category, airport_class=c.airport_class,
                known_delay_from_prev_leg=s.known_delay_source.startswith("previous leg"),
                sq_hard_fails="|".join(x.constraint for x in checks if x.hard and not x.passed),
                sq_soft_fails="|".join(x.constraint for x in checks if not x.hard and not x.passed),
                sq_holding=sq.holding_min, sq_delay=sq.revised_arrival_delay_min,
                escalated=fb is None,
                fb_holding=None if fb is None else fb.holding_min,
                fb_delay=None if fb is None else fb.revised_arrival_delay_min,
                fb_soft_fails=None if fb is None else sum(not x.passed for x in check_all(s, c, fb) if not x.hard))


def _audit_chunk(args) -> list[dict]:
    rows, planned_gate, seed = args
    return [audit_row(r, _FLIGHTS, planned_gate, seed) for _, r in rows.iterrows()]


def screen(rows: pd.DataFrame, workers: int = 8, gates_per_airline: int | None = None,
           flights: pd.DataFrame | None = None) -> pd.DataFrame:
    """audit_row on each row, results aligned with `rows` (same order). Rules only, used to pick stress flights."""
    gates = ctx_mod.GATES_PER_AIRLINE if gates_per_airline is None else gates_per_airline
    if workers <= 1:
        flights = load_flights() if flights is None else flights  # once, not per row
        return pd.DataFrame([audit_row(r, flights) for _, r in rows.iterrows()])
    chunks = [(rows.iloc[i:i + 250], "first", 0) for i in range(0, len(rows), 250)]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(gates,)) as ex:
        return pd.DataFrame([x for part in ex.map(_audit_chunk, chunks) for x in part])


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval of a proportion, in %."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(100 * (centre - half), 1), round(100 * (centre + half), 1))


def _rate(mask: pd.Series) -> dict:
    k, n = int(mask.sum()), len(mask)
    return {"pct": round(100 * k / n, 1) if n else None, "ci95": wilson(k, n), "n": n}


def summarize(df: pd.DataFrame) -> dict:
    unsafe = df["sq_hard_fails"] != ""
    fails = df["sq_hard_fails"].str.split("|").explode()
    holding = df["sq_holding"] > 0
    saved = ((df["sq_holding"] - df["fb_holding"]).clip(lower=0)
             * df["wake_category"].map(holding_burn_kg_per_min)).dropna()
    return {
        "flights": len(df),
        "status_quo_unsafe": _rate(unsafe),
        "status_quo_unsafe_by_rule": {k: _rate(df["sq_hard_fails"].str.contains(k, regex=False))
                                      for k in fails[fails != ""].value_counts().index},
        "status_quo_unsafe_by_cause": {k: _rate(g["sq_hard_fails"] != "") for k, g in df.groupby("cause")},
        "status_quo_unsafe_by_delay_source": {("prev_leg" if k else "proxy_LATE_AIRCRAFT_DELAY"): _rate(g["sq_hard_fails"] != "")
                                              for k, g in df.groupby("known_delay_from_prev_leg")},
        "escalated_no_safe_plan": _rate(df["escalated"]),
        "airborne_holding_share": _rate(holding),
        "airborne_holding_min_when_any": {"mean": round(df.loc[holding, "sq_holding"].mean(), 1) if holding.any() else None,
                                          "p50": df.loc[holding, "sq_holding"].median() if holding.any() else None,
                                          "p90": df.loc[holding, "sq_holding"].quantile(0.9) if holding.any() else None},
        "fuel_saved_kg_per_flight": {"mean": round(saved.mean()), "median": round(saved.median()),
                                     "mean_without_top_1pct": round(saved[saved <= saved.quantile(0.99)].mean())},
        "mean_delay_status_quo_vs_solver": [round(df["sq_delay"].mean(), 1), round(df["fb_delay"].mean(), 1)],
        "top_destinations_unsafe": {k: _rate(g["sq_hard_fails"] != "")
                                    for k, g in df.groupby("destination") if len(g) >= 200},
    }


def run_audit(n: int = 10_000, seed: int = 0, workers: int = 8, gates_per_airline: int | None = None,
              planned_gate: str = "first", flights: pd.DataFrame | None = None):
    flights = load_flights() if flights is None else flights
    d = disruptions(flights)
    rows = d.sample(min(n, len(d)), random_state=seed)
    if workers <= 1:  # in-process (tests)
        prev, ctx_mod.GATES_PER_AIRLINE = ctx_mod.GATES_PER_AIRLINE, gates_per_airline
        try:
            results = [audit_row(r, flights, planned_gate, seed) for _, r in rows.iterrows()]
        finally:
            ctx_mod.GATES_PER_AIRLINE = prev
    else:
        chunks = [(rows.iloc[i:i + 250], planned_gate, seed) for i in range(0, len(rows), 250)]
        with ProcessPoolExecutor(workers, initializer=_init, initargs=(gates_per_airline,)) as ex:
            results = [x for part in ex.map(_audit_chunk, chunks) for x in part]
    df = pd.DataFrame(results)
    summary = summarize(df)
    tag = f"n{len(df)}_g{gates_per_airline or 'wb'}_{planned_gate}"
    out = AUDIT_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "results.csv", index=False)
    (out / "summary.md").write_text(f"# Audit {tag} seed={seed}\n\n"
                                    + "\n".join(f"- **{k}**: {v}" for k, v in summary.items()) + "\n")
    return df, summary, out
