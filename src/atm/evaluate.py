"""Evaluation bench: run the negotiation on a stratified sample of rows and compare with baselines.

Baselines
- status quo: ATC's unilateral first offer, applied without coordination (naive_initial)
- deterministic: the non-AI fallback solver alone
- reality: ARRIVAL_DELAY / next leg DEPARTURE_DELAY recorded by the DOT (never shown to the agents)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from . import llm
from .config import ROOT
from .constraints import _minutes, check_all, hard_ok, new_arrival_min
from .context import build_context
from .data import disruptions, next_leg, row_to_disruption, _hhmm
from .fallback import deterministic_resolution
from .negotiation import naive_initial, negotiate
from .protocol import Outcome, Proposal

EVAL_DIR = ROOT / "eval"


def sample(flights: pd.DataFrame, n: int, seed: int = 0) -> pd.DataFrame:
    """Half weather, half late-aircraft rows (the file is 91% late-aircraft, so weather is oversampled)."""
    d = disruptions(flights)
    weather = d[d["WEATHER_DELAY"] > 15]
    late = d[d["WEATHER_DELAY"] <= 15]
    k = n // 2
    return pd.concat([weather.sample(k, random_state=seed), late.sample(n - k, random_state=seed)])


def _soft_fails(s, c, p: Proposal | None) -> int | None:
    return None if p is None else sum(not r.passed for r in check_all(s, c, p) if not r.hard)


def _unsafe_accepts(out: Outcome) -> int:
    """Agent said accept on a proposal that fails a hard constraint (caught by the checker)."""
    return sum(e.accept for t in out.turns if not hard_ok(t.hard_checks) for e in t.evaluations)


def run_case(flights: pd.DataFrame, r: pd.Series, agents: list | None = None) -> dict:
    s = row_to_disruption(r)
    leg = next_leg(flights, r)
    c = build_context(s, None if leg is None else _hhmm(leg["SCHEDULED_DEPARTURE"]))
    naive, fb = naive_initial(c), deterministic_resolution(s, c)
    row = dict(flight_id=s.flight_id, cause=s.cause, origin=s.origin, destination=s.destination,
               has_next_leg=leg is not None, real_arrival_delay=r["ARRIVAL_DELAY"],
               naive_hard_fails=sum(not x.passed for x in check_all(s, c, naive) if x.hard),
               fallback_holding=None if fb is None else fb.holding_min,
               fallback_delay=None if fb is None else fb.revised_arrival_delay_min,
               fallback_soft_fails=_soft_fails(s, c, fb))
    t0 = time.time()
    try:
        out = negotiate(s, c, naive, agents)
    except Exception as e:  # API error, refusal, schema failure: counted, not hidden
        return row | dict(error=f"{type(e).__name__}: {e}"[:200], latency_s=round(time.time() - t0, 1))
    p = out.final
    row |= dict(error=None, latency_s=round(time.time() - t0, 1), resolved_by=out.resolved_by,
                consensus=out.consensus, rounds=len(out.turns), unsafe_accepts=_unsafe_accepts(out),
                final_hard_ok=p is not None and hard_ok(check_all(s, c, p)),
                final_holding=None if p is None else p.holding_min,
                final_delay=None if p is None else p.revised_arrival_delay_min,
                final_soft_fails=_soft_fails(s, c, p))
    if leg is not None and p is not None:
        ready = new_arrival_min(s, p) + c.min_turnaround_min
        row |= dict(pred_next_dep_delay=max(0, ready - _minutes(c.next_departure)),
                    real_next_dep_delay=leg["DEPARTURE_DELAY"])
    return row


def summarize(df: pd.DataFrame) -> dict:
    ok = df[df["error"].isna()]
    leg = ok.dropna(subset=["pred_next_dep_delay"]) if "pred_next_dep_delay" in ok else ok.iloc[0:0]
    err = (leg["pred_next_dep_delay"] - leg["real_next_dep_delay"]) if len(leg) else pd.Series(dtype=float)
    return {
        "cases": len(df), "errors": int(df["error"].notna().sum()),
        "consensus_rate": round(ok["consensus"].mean(), 2) if len(ok) else None,
        "fallback_rate": round((ok["resolved_by"] == "deterministic_fallback").mean(), 2) if len(ok) else None,
        "consensus_within_3_rounds": int((ok["consensus"] & (ok["rounds"] <= 3)).sum()) if len(ok) else 0,
        "mean_rounds": round(ok["rounds"].mean(), 2) if len(ok) else None,
        "final_solutions_safe": f"{int(ok['final_hard_ok'].sum())}/{len(ok)}",
        "agent_unsafe_accepts_caught": int(ok["unsafe_accepts"].sum()) if len(ok) else 0,
        "status_quo_unsafe": f"{int((ok['naive_hard_fails'] > 0).sum())}/{len(ok)}",
        "mean_holding_negotiated": round(ok["final_holding"].mean(), 1) if len(ok) else None,
        "mean_holding_fallback": round(ok["fallback_holding"].mean(), 1) if len(ok) else None,
        "mean_holding_status_quo": 15,
        "mean_delay_negotiated": round(ok["final_delay"].mean(), 1) if len(ok) else None,
        "mean_delay_fallback": round(ok["fallback_delay"].mean(), 1) if len(ok) else None,
        "mean_real_arrival_delay": round(ok["real_arrival_delay"].mean(), 1) if len(ok) else None,
        "mean_soft_fails_negotiated": round(ok["final_soft_fails"].mean(), 2) if len(ok) else None,
        "mean_soft_fails_fallback": round(ok["fallback_soft_fails"].mean(), 2) if len(ok) else None,
        "next_leg_cases": len(leg),
        "next_leg_delay_MAE_min": round(err.abs().mean(), 1) if len(err) else None,
        "next_leg_delay_bias_min": round(err.mean(), 1) if len(err) else None,
        "mean_latency_s": round(ok["latency_s"].mean(), 1) if len(ok) else None,
        "llm_calls": llm.USAGE["calls"], "cost_usd": round(llm.cost_usd(), 2),
    }


def run_eval(flights: pd.DataFrame, n: int = 20, seed: int = 0, workers: int = 4, agents: list | None = None):
    rows = sample(flights, n, seed)
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda r: run_case(flights, r, agents), [r for _, r in rows.iterrows()]))
    df = pd.DataFrame(results)
    summary = summarize(df)
    out = EVAL_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "results.csv", index=False)
    (out / "summary.md").write_text(
        f"# Eval n={n} seed={seed}\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in summary.items()) + "\n")
    return df, summary, out
