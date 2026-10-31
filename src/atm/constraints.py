"""Deterministic constraints per domain. The LLM never decides legality: these do.

hard=True  -> safety rule, a proposal failing it can never be accepted.
hard=False -> cost rule, reported to the agents and traded off in negotiation.
Every check carries its basis (REGULATORY / DATA / ASSUMPTION) and its source.
"""

from __future__ import annotations

from .context import PROVENANCE
from .protocol import Basis, ConstraintResult, Disruption, OpsContext, Proposal, Role

# --- Regulatory values -------------------------------------------------------

# 14 CFR 121.639 (US domestic): fuel to destination, then alternate, then 45 min at normal cruise.
FINAL_RESERVE_MIN = 45
FINAL_RESERVE_SRC = "14 CFR 121.639 - US domestic fuel: destination + alternate + 45 min (ICAO/EASA: 30 min)"

# ICAO PANS-ATM Doc 4444 distance-based wake minima on approach, NM, (leader, follower).
# Values via SKYbrary RECAT page; US airspace uses FAA JO 7110.65 categories (to check).
WAKE_MIN_NM = {
    ("J", "H"): 6, ("J", "M"): 7, ("J", "L"): 8,
    ("H", "H"): 4, ("H", "M"): 5, ("H", "L"): 6,
    ("M", "L"): 5,
}
RADAR_MIN_NM = 3  # ICAO Doc 4444 radar separation minimum when no wake minimum applies
WAKE_SRC = "ICAO Doc 4444 wake turbulence minima (via SKYbrary); radar minimum 3 NM"

# --- Assumptions -------------------------------------------------------------

FINAL_APPROACH_SPEED_KT = 140  # typical narrowbody final approach groundspeed


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _clock(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def new_arrival_min(s: Disruption, p: Proposal) -> int:
    return _minutes(s.scheduled_arrival) + p.revised_arrival_delay_min


def _ctx_basis(field: str) -> tuple[Basis, str]:
    return PROVENANCE[field]


# --- ATC ---------------------------------------------------------------------

def check_atc(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    required_nm = WAKE_MIN_NM.get((c.leader_wake_category, c.wake_category), RADAR_MIN_NM)
    gap_nm = round(p.slot_gap_min * FINAL_APPROACH_SPEED_KT / 60, 1)
    rwy_basis, rwy_src = _ctx_basis("closed_runways")
    slot_basis, slot_src = _ctx_basis("earliest_arrival_delay_min")
    return [
        ConstraintResult(role=Role.ATC, constraint="runway_open", hard=True,
                         passed=p.runway in c.runways and p.runway not in c.closed_runways,
                         detail=f"runway {p.runway}, closed: {c.closed_runways or 'none'}",
                         basis=rwy_basis, source=rwy_src),
        ConstraintResult(role=Role.ATC, constraint="wake_separation", hard=True,
                         passed=gap_nm >= required_nm,
                         detail=f"{gap_nm} NM behind {c.leader_wake_category} (own {c.wake_category}), "
                                f"min {required_nm} NM at {FINAL_APPROACH_SPEED_KT} kt",
                         basis=Basis.REGULATORY, source=WAKE_SRC),
        ConstraintResult(role=Role.ATC, constraint="landing_slot_available", hard=True,
                         passed=p.revised_arrival_delay_min >= c.earliest_arrival_delay_min,
                         detail=f"delay {p.revised_arrival_delay_min} >= earliest slot {c.earliest_arrival_delay_min} min",
                         basis=slot_basis, source=slot_src),
        # TODO: taxiway blockage, sector throughput (AAR per hour)
    ]


# --- Pilot -------------------------------------------------------------------

def check_pilot(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    # Legal reserves (alternate + 45 min) are untouchable; only fuel above them can be spent holding.
    margin = c.holding_fuel_available_min - p.holding_min
    _, fuel_src = _ctx_basis("holding_fuel_available_min")
    return [
        ConstraintResult(role=Role.PILOT, constraint="final_reserve_fuel", hard=True,
                         passed=margin >= 0,
                         detail=f"holding {p.holding_min} min vs {c.holding_fuel_available_min} min of fuel above the "
                                f"{FINAL_RESERVE_MIN}-min reserve (margin {margin} min)",
                         basis=Basis.REGULATORY, source=f"{FINAL_RESERVE_SRC}; fuel on board: {fuel_src}"),
        # TODO: passenger connections at risk, turbulence on reroute
    ]


# --- Ground ------------------------------------------------------------------

def check_ground(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    arrival = new_arrival_min(s, p)
    gate_basis, gate_src = _ctx_basis("blocked_gates")
    crew_basis, crew_src = _ctx_basis("crew_shift_end")
    out = [
        ConstraintResult(role=Role.GROUND, constraint="gate_available", hard=True,
                         passed=p.gate in c.gates and p.gate not in c.blocked_gates,
                         detail=f"gate {p.gate}, blocked: {c.blocked_gates or 'none'}",
                         basis=gate_basis, source=gate_src),
        ConstraintResult(role=Role.GROUND, constraint="crew_shift", hard=False,
                         passed=arrival <= _minutes(c.crew_shift_end),
                         detail=f"arrival {_clock(arrival)} vs crew shift end {c.crew_shift_end}",
                         basis=crew_basis, source=crew_src),
    ]
    if c.next_departure:
        ready = arrival + c.min_turnaround_min
        nd_basis, nd_src = _ctx_basis("next_departure")
        out.append(ConstraintResult(role=Role.GROUND, constraint="turnaround_next_leg", hard=False,
                                    passed=ready <= _minutes(c.next_departure),
                                    detail=f"ready {_clock(ready)} ({c.min_turnaround_min} min turn) vs next "
                                           f"departure {c.next_departure}",
                                    basis=nd_basis, source=nd_src))
    return out


def check_all(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    return check_atc(s, c, p) + check_pilot(s, c, p) + check_ground(s, c, p)


def hard_ok(results: list[ConstraintResult]) -> bool:
    return all(r.passed for r in results if r.hard)
