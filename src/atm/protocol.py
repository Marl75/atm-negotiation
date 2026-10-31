"""Structured messages exchanged between agents. Every agent output is validated against these."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr


class Role(str, Enum):
    ATC = "ATC"
    PILOT = "PILOT"
    GROUND = "GROUND"


class DotDelayCauses(BaseModel):
    """The row's DOT delay-cause minutes, passed to the agents as the brief asks ("pass the parameters in that row").

    Attributed by the DOT after the flight, and they sum exactly to ARRIVAL_DELAY: context on the kind of disruption,
    not a forecast. No deterministic code (slot, checks, solver, audit) reads them.
    """

    weather: float
    late_aircraft: float
    air_system: float
    airline: float
    security: float
    note: str = "DOT attribution made after the flight; not available at decision time; not used by the checks"


class Disruption(BaseModel):
    """One row of the DOT 2015 dataset, turned into a negotiation scenario.

    Deterministic fields are what is known before the decision. The DOT delay-cause minutes are attached in
    `dot_delay_causes_min` for the agents only, as the brief requires, and flagged as post-hoc.
    """

    flight_id: str
    airline: str
    flight_number: int
    tail_number: str | None
    aircraft_type: str | None  # from the FAA registry, None if the tail is unknown
    origin: str
    destination: str
    scheduled_departure: str  # "HH:MM" local, origin
    scheduled_arrival: str    # "HH:MM" local, destination
    overnight: bool = False   # scheduled arrival on the day after the DOT date
    distance_nm: float
    known_departure_delay_min: int  # inbound aircraft late: earliest departure vs schedule, known before departure
    known_delay_source: str
    cause: str  # "WEATHER" (scenario: destination capacity cut) | "LATE_AIRCRAFT"
    dot_delay_causes_min: DotDelayCauses | None = None  # agents only, see DotDelayCauses


class Basis(str, Enum):
    """Where a threshold comes from. Shown in the log so judges see what is real vs simulated."""

    REGULATORY = "REGULATORY"  # published rule, cited
    DATA = "DATA"              # derived from the DOT 2015 file or the FAA registry
    ASSUMPTION = "ASSUMPTION"  # simulated value, to validate with operators


class RunwaySlot(BaseModel):
    """First-come-first-served landing slot for this flight on one runway, after the arrivals ready before it."""

    earliest_delay_min: int        # minutes after scheduled arrival
    leader_category: str | None    # FAA wake category of the arrival just ahead on this runway
    leader_flight: str | None


class OpsContext(BaseModel):
    """Operational facts the DOT file does not contain directly. Each field's basis is listed in context.py."""

    wake_category: str                  # own aircraft, FAA SUPER/HEAVY/B757/LARGE/SMALL
    airport_class: str                  # workbook size class of the destination
    runways: list[str]
    closed_runways: list[str]
    arrival_interval_min: float         # min minutes between arrivals on one runway at workbook capacity
    runway_slots: dict[str, RunwaySlot]  # open runways only
    earliest_arrival_delay_min: int     # best slot over open runways
    ready_arrival_delay_min: int        # arrival delay if the aircraft departs as soon as it is ready
    decision_min: int                   # when the plan is agreed, minutes after the DOT date's midnight
    curfew: str | None                  # "HH:MM-HH:MM" no commercial arrivals at destination
    gates: list[str]
    planned_gate: str
    gates_busy_until_min: dict[str, int]  # minutes after the DOT date's midnight; 0 = free
    holding_fuel_available_min: int     # fuel above the regulatory reserve, in minutes of holding
    crew_fdp_end_min: int | None        # flight crew: end of max flight duty period, minutes after midnight
    crew_shift_end: str                 # "HH:MM", ground crew at destination
    ground_shift_end_min: int           # same, minutes after the DOT date's midnight
    next_departure: str | None          # same tail number, same day
    min_turnaround_min: int             # workbook limit at destination
    expected_turnaround_min: int        # forecast (calibrated per airline), >= the limit


class Proposal(BaseModel):
    """A candidate resolution. Same shape whoever proposes it, so it can be checked by every domain.

    Delay not flown as airborne holding is taken on the ground at the origin, before departure (EDCT-like).
    """

    revised_arrival_delay_min: int = Field(ge=0, description="Total minutes added to scheduled arrival, holding included")
    holding_min: int = Field(ge=0, description="Airborne holding before approach (part of the delay above); "
                                               "the rest of the delay is a ground hold at the origin")
    slot_gap_min: float = Field(ge=0, description="Minutes behind the preceding arrival on the same runway")
    runway: str
    gate: str
    reroute: bool = False
    rationale: str


# Proposal fields each role owns. Disjoint, so counter-proposals from different roles can be merged.
LEVERS: dict[Role, tuple[str, ...]] = {
    Role.ATC: ("runway", "slot_gap_min", "revised_arrival_delay_min"),
    Role.PILOT: ("holding_min", "reroute"),
    Role.GROUND: ("gate",),
}


class Evaluation(BaseModel):
    """An agent's verdict on a proposal, from its own domain only."""

    role: Role
    accept: bool
    violated_constraints: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    counter_proposal: Proposal | None = None


class ConstraintResult(BaseModel):
    """Output of the deterministic (non-LLM) checker."""

    role: Role
    constraint: str
    passed: bool
    hard: bool  # hard = safety, never negotiable; soft = cost, can be traded off
    detail: str
    basis: Basis
    source: str


class Turn(BaseModel):
    round: int
    proposal: Proposal
    proposed_by: Role | str
    evaluations: list[Evaluation]
    hard_checks: list[ConstraintResult]
    next_selection: str | None = None  # why the next round's proposal was picked among the counters


class HumanDecision(BaseModel):
    """The qualified person's decision on the outcome. Agents and solver propose, a human decides (`atm run`).

    "escalated" = the solver found no plan passing every hard check: nothing to approve, the supervisor takes over.
    """

    decision: Literal["approved", "rejected", "escalated"]
    reason: str
    decided_by: str = "approach supervisor"
    decided_at: str  # UTC, ISO 8601
    auto: bool = False  # --auto-approve: no human looked at it


class Outcome(BaseModel):
    scenario: Disruption
    context: OpsContext
    turns: list[Turn]
    consensus: bool
    final: Proposal | None
    resolved_by: str  # "consensus" | "deterministic_fallback"
    fallback_reason: str | None = None  # why the deterministic fallback decided (rules of play: "log why")
    human_decision: HumanDecision | None = None  # None = pending (eval/audit never ask a human)
    _log_path: str | None = PrivateAttr(default=None)
