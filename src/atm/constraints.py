"""Deterministic constraints per domain. The LLM never decides legality: these do.

hard=True  -> safety or legal rule, a proposal failing it can never be accepted.
hard=False -> cost rule, reported to the agents and traded off in negotiation.
Every check carries its basis (REGULATORY / DATA / ASSUMPTION) and its source.
"""

from __future__ import annotations

from .context import PROVENANCE, _minutes, scheduled_arrival_min
from .protocol import Basis, ConstraintResult, Disruption, OpsContext, Proposal, Role
from . import rules as _rules
from .rules import (CURFEWS, FDP_SRC, FDP_SRC_PART117, FINAL_APPROACH_SPEED_KT, FINAL_RESERVE_MIN, FINAL_RESERVE_SRC,
                    GATE_CHANGE_NOTICE_MIN, GATE_NOTICE_SRC, GROUND_SRC, OVERTIME_FACTOR, WAKE_SRC, in_curfew,
                    required_nm)


def _clock(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}" + ("+1" if minutes >= 1440 else "")


def new_arrival_min(s: Disruption, p: Proposal) -> int:
    """Minutes after midnight of the DOT date."""
    return scheduled_arrival_min(s) + p.revised_arrival_delay_min


def _ctx_basis(field: str) -> tuple[Basis, str]:
    return PROVENANCE[field]


# --- ATC ---------------------------------------------------------------------

def check_atc(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    slot = c.runway_slots.get(p.runway)
    leader = slot.leader_category if slot else None
    required = required_nm(leader, c.wake_category)
    gap_nm = round(p.slot_gap_min * FINAL_APPROACH_SPEED_KT / 60, 1)
    rwy_basis, rwy_src = _ctx_basis("closed_runways")
    slot_basis, slot_src = _ctx_basis("runway_slots")
    out = [
        ConstraintResult(role=Role.ATC, constraint="runway_open", hard=True,
                         passed=p.runway in c.runways and p.runway not in c.closed_runways,
                         detail=f"runway {p.runway}, closed: {c.closed_runways or 'none'}",
                         basis=rwy_basis, source=rwy_src),
        ConstraintResult(role=Role.ATC, constraint="wake_separation", hard=True,
                         passed=gap_nm >= required,
                         detail=f"{gap_nm} NM behind {leader or 'no leader'} "
                                f"{f'({slot.leader_flight}) ' if slot and slot.leader_flight else ''}"
                                f"(own {c.wake_category}), min {required} NM at {FINAL_APPROACH_SPEED_KT} kt",
                         basis=Basis.REGULATORY, source=WAKE_SRC),
        ConstraintResult(role=Role.ATC, constraint="landing_slot_available", hard=True,
                         passed=slot is not None and p.revised_arrival_delay_min >= slot.earliest_delay_min,
                         detail=f"delay {p.revised_arrival_delay_min} >= earliest slot on {p.runway}: "
                                f"{slot.earliest_delay_min if slot else 'no slot (closed or unknown runway)'} min",
                         basis=slot_basis, source=slot_src),
    ]
    if s.destination in CURFEWS:
        arrival = new_arrival_min(s, p)
        out.append(ConstraintResult(role=Role.ATC, constraint="airport_curfew", hard=True,
                                    passed=not in_curfew(s.destination, arrival),
                                    detail=f"arrival {_clock(arrival)} vs {s.destination} curfew {c.curfew}",
                                    basis=Basis.REGULATORY, source=CURFEWS[s.destination][2]))
    return out  # TODO: taxiway blockage


# --- Pilot / airline dispatch ------------------------------------------------

def check_pilot(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    # The final reserve is untouchable; only fuel above it can be spent holding.
    margin = c.holding_fuel_available_min - p.holding_min
    ground_hold = p.revised_arrival_delay_min - p.holding_min - c.ready_arrival_delay_min
    _, fuel_src = _ctx_basis("holding_fuel_available_min")
    ready_basis, ready_src = _ctx_basis("ready_arrival_delay_min")
    out = [
        ConstraintResult(role=Role.PILOT, constraint="final_reserve_fuel", hard=True,
                         passed=margin >= 0,
                         detail=f"holding {p.holding_min} min vs {c.holding_fuel_available_min} min of fuel above the "
                                f"{FINAL_RESERVE_MIN}-min reserve (margin {margin} min)",
                         basis=Basis.REGULATORY, source=f"{FINAL_RESERVE_SRC}; fuel on board: {fuel_src}"),
        ConstraintResult(role=Role.PILOT, constraint="departure_feasible", hard=True,
                         passed=ground_hold >= 0,
                         detail=f"ground hold at {s.origin} = {ground_hold} min (delay {p.revised_arrival_delay_min} "
                                f"- holding {p.holding_min} - aircraft ready +{c.ready_arrival_delay_min}); "
                                "cannot depart before the aircraft is ready",
                         basis=ready_basis, source=ready_src),
    ]
    if c.crew_fdp_end_min is not None:
        arrival = new_arrival_min(s, p)
        out.append(ConstraintResult(role=Role.PILOT, constraint="flight_crew_duty", hard=True,
                                    passed=arrival <= c.crew_fdp_end_min,
                                    detail=f"block-in {_clock(arrival)} vs max FDP end {_clock(c.crew_fdp_end_min)}",
                                    basis=Basis.REGULATORY,
                                    source=FDP_SRC if _rules.CREW_DUTY_MODEL == "workbook" else FDP_SRC_PART117))
    return out  # TODO: passenger connections, turbulence on reroute


# --- Ground ------------------------------------------------------------------

def check_ground(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    arrival = new_arrival_min(s, p)
    busy = c.gates_busy_until_min.get(p.gate)
    gate_basis, gate_src = _ctx_basis("gates_busy_until_min")
    done = arrival + c.min_turnaround_min  # ramp work on this aircraft ends after the minimum turnaround
    out = [
        ConstraintResult(role=Role.GROUND, constraint="gate_available", hard=True,
                         passed=busy is not None and arrival >= busy,
                         detail=f"gate {p.gate} at {_clock(arrival)}, "
                                f"{'unknown gate' if busy is None else f'busy until {_clock(busy)}' if busy else 'free'}",
                         basis=gate_basis, source=gate_src),
        ConstraintResult(role=Role.GROUND, constraint="crew_shift", hard=False,
                         passed=done <= c.ground_shift_end_min,
                         detail=f"turnaround work ends {_clock(done)} vs ground shift end {c.crew_shift_end}"
                                + ("" if done <= c.ground_shift_end_min else
                                   f": {done - c.ground_shift_end_min} min of overtime at {OVERTIME_FACTOR:g}x"),
                         basis=Basis.DATA, source=GROUND_SRC),
    ]
    if p.gate != c.planned_gate:
        notice = arrival - c.decision_min
        out.append(ConstraintResult(role=Role.GROUND, constraint="gate_change_notice", hard=True,
                                    passed=notice >= GATE_CHANGE_NOTICE_MIN,
                                    detail=f"gate {c.planned_gate} -> {p.gate} decided {notice} min before arrival "
                                           f"(min {GATE_CHANGE_NOTICE_MIN})",
                                    basis=Basis.DATA, source=GATE_NOTICE_SRC))
    if c.next_departure:
        ready = arrival + c.min_turnaround_min
        _, nd_src = _ctx_basis("next_departure")
        out.append(ConstraintResult(role=Role.GROUND, constraint="turnaround_next_leg", hard=False,
                                    passed=ready <= _minutes(c.next_departure),
                                    detail=f"ready {_clock(ready)} ({c.min_turnaround_min} min minimum turnaround) "
                                           f"vs next departure {c.next_departure}",
                                    basis=Basis.DATA, source=f"{nd_src}; turnaround limit: {_ctx_basis('min_turnaround_min')[1]}"))
    return out


def check_all(s: Disruption, c: OpsContext, p: Proposal) -> list[ConstraintResult]:
    return check_atc(s, c, p) + check_pilot(s, c, p) + check_ground(s, c, p)


def hard_ok(results: list[ConstraintResult]) -> bool:
    return all(r.passed for r in results if r.hard)
