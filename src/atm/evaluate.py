"""Evaluation bench: run the negotiation on a stratified sample of rows and compare with baselines.

Baselines
- status quo: no coordination - depart when ready, wait for the first-come-first-served slot in airborne holding,
  keep the planned gate (naive_initial). Separation is respected; its failures are measured, not constructed.
- deterministic: the non-AI fallback solver alone
- reality: ARRIVAL_DELAY / DEPARTURE_DELAY / next leg DEPARTURE_DELAY recorded by the DOT (never shown to the agents)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from . import llm
from .config import ROOT
from .constraints import _minutes, check_all, hard_ok, new_arrival_min
from .data import build_scenario, disruptions, next_leg
from .fallback import deterministic_resolution
from .negotiation import naive_initial, negotiate
from .protocol import Outcome, Proposal

EVAL_DIR = ROOT / "eval"
HOLDING_FUEL_KG_PER_MIN = 40  # ASSUMPTION: A320-class holding burn ~2.4 t/h; a ground hold burns ~0 (APU aside)


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


def _who(x) -> str:
    return getattr(x, "value", x)


def _final_author(out: Outcome) -> str:
    """Who authored the adopted proposal: an agent, MERGED, GROUND_HOLD<agent>, SOLVER, or FALLBACK."""
    return _who(out.turns[-1].proposed_by) if out.consensus else "FALLBACK"


def _hard_fails(s, c, p: Proposal | None) -> list[str]:
    return [] if p is None else [r.constraint for r in check_all(s, c, p) if r.hard and not r.passed]


def run_case(flights: pd.DataFrame, r: pd.Series, agents: list | None = None) -> dict:
    s, c = build_scenario(flights, r)
    leg = next_leg(flights, r)
    naive, fb = naive_initial(s, c), deterministic_resolution(s, c)
    row = dict(flight_id=s.flight_id, cause=s.cause, origin=s.origin, destination=s.destination,
               aircraft_type=s.aircraft_type, wake_category=c.wake_category,
               known_delay_from_prev_leg=s.known_delay_source.startswith("previous leg"),
               known_departure_delay=s.known_departure_delay_min, real_departure_delay=r["DEPARTURE_DELAY"],
               slot_delay=c.earliest_arrival_delay_min, real_arrival_delay=r["ARRIVAL_DELAY"],
               has_next_leg=leg is not None,
               status_quo_holding=naive.holding_min, status_quo_hard_fails="|".join(_hard_fails(s, c, naive)),
               escalated=fb is None,
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
                final_author=_final_author(out),
                picks="|".join(_who(t.proposed_by) for t in out.turns[1:]),  # winner of each selection
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


PREV, PROXY = "prev_leg", "proxy_LATE_AIRCRAFT_DELAY_leaky"


def _by_source(ok: pd.DataFrame, metric) -> dict:
    """Reality metrics split by where the known delay came from.

    PROXY rows use LATE_AIRCRAFT_DELAY, one of the 5 cause columns that sum exactly to ARRIVAL_DELAY:
    the input contains part of the answer, so their accuracy is not claimable. Headline = PREV only.
    """
    out = {}
    for name, part in ((PREV, ok[ok["known_delay_from_prev_leg"]]), (PROXY, ok[~ok["known_delay_from_prev_leg"]])):
        v = metric(part)
        out[name] = {"n": len(part), "value": None if v is None or pd.isna(v) else round(float(v), 1)}
    return out


def summarize(df: pd.DataFrame) -> dict:
    ok = df[df["error"].isna()]
    solved = ok[~ok["escalated"]]
    leg = ok.dropna(subset=["pred_next_dep_delay"]) if "pred_next_dep_delay" in ok else ok.iloc[0:0]
    err = (leg["pred_next_dep_delay"] - leg["real_next_dep_delay"]) if len(leg) else pd.Series(dtype=float)
    mean = lambda s, d=1: round(s.mean(), d) if len(s) else None
    nl = lambda p: ((p["pred_next_dep_delay"] - p["real_next_dep_delay"]).abs().mean()
                    if "pred_next_dep_delay" in p and p["pred_next_dep_delay"].notna().any() else None)
    authors = ok["final_author"] if "final_author" in ok else pd.Series(dtype=str)
    picks = ok["picks"].str.split("|").explode() if "picks" in ok else pd.Series(dtype=str)
    sq_fails = ok["status_quo_hard_fails"].str.split("|").explode()
    holding_saved = (ok["status_quo_holding"] - ok["final_holding"]).dropna()
    return {
        "cases": len(df), "errors": int(df["error"].notna().sum()),
        "consensus_rate": mean(ok["consensus"], 2),
        "fallback_rate": mean(ok["resolved_by"] == "deterministic_fallback", 2),
        "consensus_within_3_rounds": int((ok["consensus"] & (ok["rounds"] <= 3)).sum()),
        "mean_rounds": mean(ok["rounds"], 2),
        "escalated_to_human_no_safe_option": f"{int(ok['escalated'].sum())}/{len(ok)}",
        "final_solutions_safe_when_solvable": f"{int(solved['final_hard_ok'].sum())}/{len(solved)}",
        "agent_unsafe_accepts_caught": int(ok["unsafe_accepts"].sum()) if len(ok) else 0,
        "status_quo_unsafe": f"{int((ok['status_quo_hard_fails'] != '').sum())}/{len(ok)}",
        "status_quo_failures": sq_fails[sq_fails != ""].value_counts().to_dict(),
        "mean_holding_status_quo": mean(ok["status_quo_holding"]),
        "mean_holding_negotiated": mean(ok["final_holding"].dropna()),
        "mean_holding_fallback": mean(ok["fallback_holding"].dropna()),
        "fuel_saved_kg_per_flight_vs_status_quo": mean(holding_saved * HOLDING_FUEL_KG_PER_MIN, 0),
        "mean_delay_negotiated": mean(ok["final_delay"].dropna()),
        "mean_delay_fallback": mean(ok["fallback_delay"].dropna()),
        "mean_soft_fails_negotiated": mean(ok["final_soft_fails"].dropna(), 2),
        "mean_soft_fails_fallback": mean(ok["fallback_soft_fails"].dropna(), 2),
        # Who authored the adopted solution: did the agents negotiate it, or did the orchestrator?
        "final_author_share": authors.value_counts(normalize=True).round(2).to_dict(),
        "mean_holding_by_final_author": ok.groupby("final_author")["final_holding"].mean().round(1).to_dict()
                                        if len(authors) else {},
        "selection_picks": picks[picks != ""].value_counts().to_dict(),
        "known_delay_from_prev_leg_share": mean(ok["known_delay_from_prev_leg"], 2),
        # Reality comparisons: headline is prev_leg only; the proxy rows leak the answer
        "known_departure_delay_MAE_vs_real_min": _by_source(
            ok, lambda p: (p["known_departure_delay"] - p["real_departure_delay"]).abs().mean()),
        "slot_model_MAE_vs_real_arrival_min": _by_source(
            ok, lambda p: (p["slot_delay"] - p["real_arrival_delay"]).abs().mean()),
        "slot_model_bias_vs_real_arrival_min": _by_source(ok, lambda p: (p["slot_delay"] - p["real_arrival_delay"]).mean()),
        "slot_exact_match_share": _by_source(ok, lambda p: (p["slot_delay"] == p["real_arrival_delay"]).mean() * 100),
        "aircraft_type_from_faa_registry": mean(ok["aircraft_type"].notna(), 2),
        "next_leg_cases": len(leg),
        "next_leg_delay_MAE_min": _by_source(ok, nl),
        "next_leg_delay_bias_min": mean(err),
        "mean_latency_s": mean(ok["latency_s"]),
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
