"""Evaluation bench: run the negotiation on a stratified sample of rows and compare with baselines.

Baselines
- status quo: no coordination - depart when ready, wait for the first-come-first-served slot in airborne holding,
  keep the planned gate (naive_initial). Separation is respected; its failures are measured, not constructed.
- deterministic: the non-AI fallback solver alone
- reality: ARRIVAL_DELAY / DEPARTURE_DELAY / next leg DEPARTURE_DELAY recorded by the DOT (never shown to the agents)
"""

from __future__ import annotations

import json
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
# Holding burn by aircraft class from the challenge workbook (2.4 t/h narrowbody, 6.5 t/h widebody); a ground hold
# burns ~0 (APU aside)
from .rules import holding_burn_kg_per_min


def sample(flights: pd.DataFrame, n: int, seed: int = 0) -> pd.DataFrame:
    """Half weather, half late-aircraft rows (the file is 91% late-aircraft, so weather is oversampled)."""
    d = disruptions(flights)
    weather = d[d["WEATHER_DELAY"] > 15]
    late = d[d["WEATHER_DELAY"] <= 15]
    k = n // 2
    return pd.concat([weather.sample(k, random_state=seed), late.sample(n - k, random_state=seed)])


POPULATIONS = ("stratified", "prev_leg", "stress")


def populations(flights: pd.DataFrame, population: str, n: int, samples: int = 1, seed: int = 0,
                workers: int = 8, pool_size: int | None = None) -> list[pd.DataFrame]:
    """`samples` disjoint samples of n flights.

    - stratified: half weather, half late aircraft, all rows
    - prev_leg: same, only rows whose inbound delay comes from the previous leg (no LATE_AIRCRAFT_DELAY leak)
    - stress: flights where the uncoordinated plan breaks a hard rule or flies airborne holding, screened by the
      rules alone (audit) on a random pool - where coordination has something to do
    """
    d = disruptions(flights)
    if population == "prev_leg":
        d = d[d["KNOWN_DELAY_SRC"].str.startswith("previous leg")]
    if population == "stress":
        from .audit import screen  # rules only, no LLM
        pool = d.sample(min(len(d), pool_size or max(6000, 40 * n * samples)), random_state=seed)
        res = screen(pool, workers, flights=flights)
        shuffled = pool[((res["sq_hard_fails"] != "") | (res["sq_holding"] > 0)).to_numpy()].sample(
            frac=1, random_state=seed)
        if len(shuffled) < n * samples:
            raise ValueError(f"only {len(shuffled)} stress flights in the pool for {n * samples} requested")
        return [shuffled.iloc[i * n:(i + 1) * n] for i in range(samples)]
    weather = d[d["WEATHER_DELAY"] > 15].sample(frac=1, random_state=seed)
    late = d[d["WEATHER_DELAY"] <= 15].sample(frac=1, random_state=seed)
    k = n // 2
    return [pd.concat([weather.iloc[i * k:(i + 1) * k], late.iloc[i * (n - k):(i + 1) * (n - k)]])
            for i in range(samples)]


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


def run_case(flights: pd.DataFrame, r: pd.Series, agents: list | None = None,
             outcome: Outcome | None = None) -> dict:
    """`outcome`: an already-run negotiation (rebuilt from its log) instead of calling the agents again."""
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
        out = outcome if outcome is not None else negotiate(s, c, naive, agents)
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
    ok = df[df["error"].isna()].copy()
    if ok.empty:  # every flight errored or hit the budget cap
        return {"cases": len(df), "errors": int(df["error"].notna().sum()),
                "error_kinds": df["error"].value_counts().to_dict()}
    # error / budget-cap rows lack these columns: the mix turns them into objects, where ~ is integer NOT
    for col in ("escalated", "consensus", "final_hard_ok", "known_delay_from_prev_leg"):
        if col in ok:
            ok[col] = ok[col].fillna(False).astype(bool)
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
        "fuel_saved_kg_per_flight_vs_status_quo": mean(
            holding_saved * ok.loc[holding_saved.index, "wake_category"].map(holding_burn_kg_per_min), 0),
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


def run_eval(flights: pd.DataFrame, n: int = 20, seed: int = 0, workers: int = 4, agents: list | None = None,
             rows: pd.DataFrame | None = None, tag: str = "", max_cost_usd: float | None = None):
    """One eval run. `rows` overrides the default stratified sample. `max_cost_usd` caps this run's API spend:
    once reached, remaining flights are recorded as errors ("budget cap") instead of calling the API."""
    rows = sample(flights, n, seed) if rows is None else rows
    calls0, in0, out0 = llm.USAGE["calls"], llm.USAGE["input_tokens"], llm.USAGE["output_tokens"]
    spent = lambda: ((llm.USAGE["input_tokens"] - in0) * llm.PRICE_IN + (llm.USAGE["output_tokens"] - out0) * llm.PRICE_OUT) / 1e6

    def case(r):
        if max_cost_usd is not None and spent() >= max_cost_usd:
            return dict(flight_id=r["AIRLINE"] + str(r["FLIGHT_NUMBER"]), error="budget cap reached, not run")
        return run_case(flights, r, agents)

    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(case, [r for _, r in rows.iterrows()]))
    df = pd.DataFrame(results)
    out = EVAL_DIR / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + (f"_{tag}" if tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "results.csv", index=False)  # before summarizing: a summary bug must not lose paid results
    summary = summarize(df) | {"llm_calls": llm.USAGE["calls"] - calls0, "cost_usd": round(spent(), 2)}
    (out / "summary.md").write_text(
        f"# Eval n={len(rows)} seed={seed} {tag}\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in summary.items()) + "\n")
    return df, summary, out


REPORT_KEYS = ["cases", "errors", "consensus_rate", "mean_rounds", "final_solutions_safe_when_solvable",
               "escalated_to_human_no_safe_option", "status_quo_unsafe", "agent_unsafe_accepts_caught",
               "mean_holding_status_quo", "mean_holding_negotiated", "mean_holding_fallback",
               "mean_delay_negotiated", "mean_soft_fails_negotiated", "mean_soft_fails_fallback",
               "final_author_share", "slot_model_MAE_vs_real_arrival_min", "slot_exact_match_share",
               "next_leg_cases", "next_leg_delay_MAE_min", "mean_latency_s"]


def aggregate(dirs: list) -> str:
    """Markdown report over several eval runs (disjoint samples): one column per sample, then all pooled."""
    import re
    from pathlib import Path

    dfs, cols, costs = [], [], []
    for d in map(Path, dirs):
        df = pd.read_csv(d / "results.csv")
        for c in ("status_quo_hard_fails", "picks"):  # "" (no failure / no pick) comes back from CSV as NaN
            if c in df:
                df[c] = df[c].fillna("")
        dfs.append(df)
        cols.append(summarize(df))
        m = re.search(r"cost_usd\*\*: ([0-9.]+)", (d / "summary.md").read_text())
        costs.append(float(m.group(1)) if m else float("nan"))
    pooled = summarize(pd.concat(dfs, ignore_index=True))
    fmt = lambda v: "—" if v is None else str(v)
    head = "| metric | " + " | ".join(f"sample {i + 1}" for i in range(len(cols))) + " | **pooled** |"
    lines = [head, "|" + "---|" * (len(cols) + 2)]
    for k in REPORT_KEYS:
        lines.append(f"| {k} | " + " | ".join(fmt(c.get(k)) for c in cols) + f" | **{fmt(pooled.get(k))}** |")
    lines.append("| cost_usd | " + " | ".join(f"{c:.2f}" for c in costs) + f" | **{sum(costs):.2f}** |")
    return "\n".join(lines)


def outcome_from_log(path) -> Outcome:
    """Rebuild a negotiation Outcome from its JSONL log (turns, then the outcome line), with no API call."""
    from .protocol import Turn

    lines = [x for x in open(path).read().splitlines() if x.strip()]
    return Outcome(**json.loads(lines[-1]), turns=[Turn(**json.loads(x)) for x in lines[:-1]])
