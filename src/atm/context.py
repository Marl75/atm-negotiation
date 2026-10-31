"""Build the operational context the DOT file lacks. Every field says whether it is data or an assumption."""

from __future__ import annotations

from .protocol import Basis, Disruption, OpsContext

# field -> (basis, why). Printed in the README and attached to the log.
PROVENANCE: dict[str, tuple[Basis, str]] = {
    "wake_category": (Basis.ASSUMPTION, "DOT has no aircraft type; inferred from distance (> 2500 NM -> H, else M)"),
    "leader_wake_category": (Basis.ASSUMPTION, "Simulated: Heavy ahead on final (worst common case for a Medium)"),
    "runways": (Basis.ASSUMPTION, "Generic runway names; real layouts not loaded yet"),
    "closed_runways": (Basis.ASSUMPTION, "Weather row -> one runway closed, to create a disruption"),
    "gates": (Basis.ASSUMPTION, "Simulated gate pool"),
    "blocked_gates": (Basis.ASSUMPTION, "Late-aircraft row -> scheduled gate still occupied"),
    "earliest_arrival_delay_min": (Basis.DATA, "WEATHER_DELAY + LATE_AIRCRAFT_DELAY of the row (PDF: pass the row parameters)"),
    "holding_fuel_available_min": (Basis.ASSUMPTION, "Discretionary fuel above legal reserves; to validate with airline dispatch"),
    "crew_shift_end": (Basis.ASSUMPTION, "Simulated end of ground-crew shift at destination"),
    "next_departure": (Basis.DATA, "Next leg of the same TAIL_NUMBER on the same day in flights.csv"),
    "min_turnaround_min": (Basis.ASSUMPTION, "Typical narrowbody turnaround 30-45 min; airline-specific"),
}


def infer_wake_category(distance_nm: float) -> str:
    return "H" if distance_nm > 2500 else "M"


def build_context(s: Disruption, next_departure: str | None = None) -> OpsContext:
    runways = ["R1", "R2"]
    gates = ["G1", "G2", "G3", "G4"]
    return OpsContext(
        wake_category=infer_wake_category(s.distance_nm),
        leader_wake_category="H",
        runways=runways,
        closed_runways=["R1"] if s.cause == "WEATHER" else [],
        gates=gates,
        blocked_gates=["G1"] if s.cause == "LATE_AIRCRAFT" else [],
        earliest_arrival_delay_min=int(s.weather_delay_min + s.late_aircraft_delay_min),
        holding_fuel_available_min=20,
        crew_shift_end="23:00",
        next_departure=next_departure,
        min_turnaround_min=35,
    )
