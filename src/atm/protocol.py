"""Structured messages exchanged between agents. Every agent output is validated against these."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    ATC = "ATC"
    PILOT = "PILOT"
    GROUND = "GROUND"


class Disruption(BaseModel):
    """One row of the DOT 2015 dataset, turned into a negotiation scenario."""

    flight_id: str
    airline: str
    flight_number: int
    tail_number: str | None
    origin: str
    destination: str
    scheduled_arrival: str  # "HH:MM" local
    scheduled_departure: str
    distance_nm: float
    weather_delay_min: float
    late_aircraft_delay_min: float
    air_system_delay_min: float
    cause: str  # "WEATHER" | "LATE_AIRCRAFT"


class Basis(str, Enum):
    """Where a threshold comes from. Shown in the log so judges see what is real vs simulated."""

    REGULATORY = "REGULATORY"  # published rule, cited
    DATA = "DATA"              # derived from the DOT 2015 row / file
    ASSUMPTION = "ASSUMPTION"  # simulated value, to validate with operators


class OpsContext(BaseModel):
    """Operational facts the DOT file does not contain. Each field's basis is listed in context.py."""

    wake_category: str            # own aircraft, ICAO L/M/H/J
    leader_wake_category: str     # aircraft ahead on final
    runways: list[str]
    closed_runways: list[str]
    gates: list[str]
    blocked_gates: list[str]
    earliest_arrival_delay_min: int   # no landing slot before this
    holding_fuel_available_min: int   # fuel above the regulatory reserve, in minutes of holding
    crew_shift_end: str               # "HH:MM", ground crew at destination
    next_departure: str | None        # same tail number, same day
    min_turnaround_min: int


class Proposal(BaseModel):
    """A candidate resolution. Same shape whoever proposes it, so it can be checked by every domain."""

    revised_arrival_delay_min: int = Field(ge=0, description="Total minutes added to scheduled arrival, holding included")
    holding_min: int = Field(ge=0, description="Airborne holding before approach (part of the delay above)")
    slot_gap_min: float = Field(ge=0, description="Minutes behind the preceding arrival on the same runway")
    runway: str
    gate: str
    reroute: bool = False
    rationale: str


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


class Outcome(BaseModel):
    scenario: Disruption
    context: OpsContext
    turns: list[Turn]
    consensus: bool
    final: Proposal | None
    resolved_by: str  # "consensus" | "deterministic_fallback"
