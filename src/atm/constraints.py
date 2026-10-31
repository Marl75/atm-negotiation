"""Deterministic hard constraints per domain. The LLM never decides legality: these do.

Thresholds are placeholders to refine (cite ICAO Doc 4444 / FAA 7110.65 in the pitch).
"""

from __future__ import annotations

from .protocol import ConstraintResult, Disruption, Proposal, Role

# TODO: refine with real values / sources
MIN_FINAL_RESERVE_MIN = 30          # ICAO final reserve fuel ~30 min holding
MAX_HOLDING_MIN = 45
MAX_CREW_EXTRA_MIN = 60             # ground crew overtime budget
CLOSED_RUNWAYS: set[str] = set()     # filled from the scenario
BLOCKED_GATES: set[str] = set()


def check_atc(s: Disruption, p: Proposal) -> list[ConstraintResult]:
    return [
        ConstraintResult(role=Role.ATC, constraint="runway_open", passed=p.runway not in CLOSED_RUNWAYS,
                         detail=f"runway {p.runway}"),
        ConstraintResult(role=Role.ATC, constraint="max_holding", passed=p.holding_min <= MAX_HOLDING_MIN,
                         detail=f"{p.holding_min} <= {MAX_HOLDING_MIN} min"),
        # TODO: wake separation slot check, taxiway blockage, sector throughput
    ]


def check_pilot(s: Disruption, p: Proposal, fuel_on_arrival_min: float = 75) -> list[ConstraintResult]:
    remaining = fuel_on_arrival_min - p.holding_min
    return [
        ConstraintResult(role=Role.PILOT, constraint="final_reserve_fuel", passed=remaining >= MIN_FINAL_RESERVE_MIN,
                         detail=f"{remaining} min fuel left vs {MIN_FINAL_RESERVE_MIN} min reserve"),
        # TODO: passenger connections at risk, turbulence on reroute
    ]


def check_ground(s: Disruption, p: Proposal) -> list[ConstraintResult]:
    return [
        ConstraintResult(role=Role.GROUND, constraint="gate_available", passed=p.gate not in BLOCKED_GATES,
                         detail=f"gate {p.gate}"),
        ConstraintResult(role=Role.GROUND, constraint="crew_overtime",
                         passed=p.revised_arrival_delay_min <= MAX_CREW_EXTRA_MIN,
                         detail=f"{p.revised_arrival_delay_min} <= {MAX_CREW_EXTRA_MIN} min"),
        # TODO: turnaround time vs next departure of same tail number
    ]


def check_all(s: Disruption, p: Proposal) -> list[ConstraintResult]:
    return check_atc(s, p) + check_pilot(s, p) + check_ground(s, p)
