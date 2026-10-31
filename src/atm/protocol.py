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


class Proposal(BaseModel):
    """A candidate resolution. Same shape whoever proposes it, so it can be checked by every domain."""

    revised_arrival_delay_min: int = Field(ge=0, description="Minutes added to scheduled arrival")
    holding_min: int = Field(ge=0, description="Airborne holding before approach")
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
    detail: str


class Turn(BaseModel):
    round: int
    proposal: Proposal
    proposed_by: Role | str
    evaluations: list[Evaluation]
    hard_checks: list[ConstraintResult]


class Outcome(BaseModel):
    scenario: Disruption
    turns: list[Turn]
    consensus: bool
    final: Proposal | None
    resolved_by: str  # "consensus" | "deterministic_fallback"
