"""Build the operational context the DOT file lacks. Every field says whether it is data or an assumption."""

from __future__ import annotations

from .aircraft import category_from_model, heuristic_category
from .protocol import Basis, Disruption, OpsContext
from .rules import CURFEWS
from .traffic import Arrival, gate_occupancy, sequence, spacing_factor

GATES_PER_AIRLINE = 4      # ASSUMPTION: gates this airline can use at the destination
HOLDING_FUEL_MIN = 20      # ASSUMPTION: discretionary fuel above legal reserves
MIN_TURNAROUND_MIN = 35    # ASSUMPTION: typical narrowbody turnaround 30-45 min
GROUND_CREW_SHIFT_END = "23:00"  # ASSUMPTION

# field -> (basis, why). Printed in the README and attached to the log.
PROVENANCE: dict[str, tuple[Basis, str]] = {
    "wake_category": (Basis.DATA, "FAA registry type for the tail number (60% of rows); "
                                  "else ASSUMPTION: airline + distance (long-haul -> HEAVY, else LARGE)"),
    "runways": (Basis.ASSUMPTION, "Arrival runways by airport size in the file (>8000 rows: 3, >1000: 2, else 1)"),
    "closed_runways": (Basis.ASSUMPTION, "Weather row -> one runway closed at destination (the DOT cause does not "
                                         "say where the weather was: origin, en route or destination)"),
    "runway_slots": (Basis.DATA, "First-come-first-served sequence of the arrivals in the file ready before ours "
                                 "(same airport and day), FAA wake spacing; on-time traffic absent from the file "
                                 "loads each runway at 70%, saturating when one closes (ASSUMPTION)"),
    "earliest_arrival_delay_min": (Basis.DATA, "Best runway slot above - no DOT delay-cause minutes used"),
    "ready_arrival_delay_min": (Basis.DATA, "Previous leg of the same tail landed late + turnaround "
                                            "(else LATE_AIRCRAFT_DELAY as proxy for the inbound ETA)"),
    "curfew": (Basis.REGULATORY, "Airport noise ordinance (rules.CURFEWS)"),
    "gates": (Basis.ASSUMPTION, f"{GATES_PER_AIRLINE} gates for the airline at destination"),
    "planned_gate": (Basis.ASSUMPTION, "First gate of the pool"),
    "gates_busy_until_min": (Basis.DATA, "Same-airline arrivals sequenced ahead of ours hold a gate for one "
                                         "turnaround"),
    "holding_fuel_available_min": (Basis.ASSUMPTION, "Discretionary fuel above legal reserves; "
                                                     "to validate with airline dispatch"),
    "crew_fdp_end_min": (Basis.REGULATORY, "14 CFR 117 Table B; crew assumed to follow the aircraft (report 1 h "
                                           "before its first departure in the file), with a fresh crew wherever the "
                                           "schedule itself would exceed the limit"),
    "crew_shift_end": (Basis.ASSUMPTION, "Simulated end of ground-crew shift at destination"),
    "next_departure": (Basis.DATA, "Next leg of the same TAIL_NUMBER on the same day in flights.csv"),
    "min_turnaround_min": (Basis.ASSUMPTION, "Typical narrowbody turnaround 30-45 min; airline-specific"),
}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def scheduled_arrival_min(s: Disruption) -> int:
    return _minutes(s.scheduled_arrival) + 1440 * s.overnight


def wake_category(s: Disruption) -> str:
    if s.aircraft_type:
        return category_from_model(s.aircraft_type)
    return heuristic_category(s.airline, s.distance_nm / 0.868976)


def build_context(s: Disruption, bank: list[Arrival] = (), n_runways: int = 2, next_departure: str | None = None,
                  crew_fdp_end_min: int | None = None) -> OpsContext:
    runways = [f"R{i + 1}" for i in range(n_runways)]
    weather = s.cause == "WEATHER"
    closed = runways[:1] if weather and n_runways > 1 else []
    open_rwys = [r for r in runways if r not in closed]
    sched = scheduled_arrival_min(s)
    own = Arrival(s.flight_id, s.airline, sched + s.known_departure_delay_min, wake_category(s))
    slots, landed = sequence(list(bank), own, sched, open_rwys, spacing_factor(n_runways, len(open_rwys), weather))
    gates = [f"G{i + 1}" for i in range(GATES_PER_AIRLINE)]
    curfew = CURFEWS.get(s.destination)
    return OpsContext(
        wake_category=own.category,
        runways=runways,
        closed_runways=closed,
        runway_slots=slots,
        earliest_arrival_delay_min=min(x.earliest_delay_min for x in slots.values()),
        ready_arrival_delay_min=s.known_departure_delay_min,
        curfew=curfew and f"{curfew[0] // 60:02d}:{curfew[0] % 60:02d}-{curfew[1] // 60:02d}:{curfew[1] % 60:02d}",
        gates=gates,
        planned_gate=gates[0],
        gates_busy_until_min=gate_occupancy(landed, s.airline, gates, MIN_TURNAROUND_MIN),
        holding_fuel_available_min=HOLDING_FUEL_MIN,
        crew_fdp_end_min=crew_fdp_end_min,
        crew_shift_end=GROUND_CREW_SHIFT_END,
        next_departure=next_departure,
        min_turnaround_min=MIN_TURNAROUND_MIN,
    )
