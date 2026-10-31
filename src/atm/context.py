"""Build the operational context the DOT file lacks. Every field says whether it is data or an assumption.

Limits come from the challenge workbook (workbook.py); deviations are listed in workbook.DEVIATIONS.
"""

from __future__ import annotations

import zlib

from . import workbook as wb
from .aircraft import category_from_model, heuristic_category
from .calibration import SOURCE as TURNAROUND_SOURCE, turnaround_min
from .protocol import Basis, Disruption, OpsContext
from .rules import (CURFEWS, FINAL_RESERVE_MIN, GROUND_SHIFT_H, GROUND_SHIFT_STARTS_H, SPARE_FUEL_ON_ARRIVAL_MIN)
from .traffic import Arrival, arrival_interval_min, gate_occupancy, sequence

GATES_PER_AIRLINE: int | None = None  # None = workbook gates x airline share; an int overrides (audit sensitivity)
DEFAULT_AIRLINE_SHARE = 0.25          # ASSUMPTION when the share is not computed from the file
FREE_GATES_SHOWN = 3                  # free airline gates listed to the ground agent, besides the spare gates

# field -> (basis, why). Printed in the README and attached to the log.
PROVENANCE: dict[str, tuple[Basis, str]] = {
    "wake_category": (Basis.DATA, "FAA registry type for the tail number (60% of rows); "
                                  "else ASSUMPTION: airline + distance (long-haul -> HEAVY, else LARGE)"),
    "airport_class": (Basis.DATA, f"{wb.SRC}, airport_capacity: size class of the destination"),
    "runways": (Basis.DATA, f"{wb.SRC}, airport_capacity: active_runways at destination"),
    "closed_runways": (Basis.ASSUMPTION, "Weather row -> one runway closed at destination (the DOT cause does not "
                                         "say where the weather was: origin, en route or destination)"),
    "arrival_interval_min": (Basis.DATA, f"{wb.SRC}: max_runway_ops_per_hour / active_runways, half of the "
                                         "movements being arrivals (ASSUMPTION); x1.5 on a one-runway airport in "
                                         "weather (ASSUMPTION)"),
    "runway_slots": (Basis.DATA, "First-come-first-served sequence of the arrivals in the file ready before ours "
                                 "(same airport and day), spaced by max(FAA wake separation, workbook capacity "
                                 "interval)"),
    "earliest_arrival_delay_min": (Basis.DATA, "Best runway slot above - no DOT delay-cause minutes used"),
    "ready_arrival_delay_min": (Basis.DATA, "Previous leg of the same tail landed late + expected turnaround "
                                            "(else LATE_AIRCRAFT_DELAY as proxy for the inbound ETA)"),
    "decision_min": (Basis.ASSUMPTION, "The plan is agreed when the aircraft is ready to leave the origin "
                                       "(scheduled departure + known departure delay)"),
    "curfew": (Basis.REGULATORY, "Airport noise ordinance (rules.CURFEWS), not in the workbook"),
    "gates": (Basis.DATA, f"{wb.SRC}: airport gates x airline's share of arrivals there in flights.csv; the "
                          "airport's spare_gates_at_any_time are listed as SPARE gates, always free"),
    "planned_gate": (Basis.ASSUMPTION, "One of the airline's gates, fixed per flight (hash of the flight id)"),
    "gates_busy_until_min": (Basis.DATA, "Same-airline arrivals sequenced ahead of ours hold a gate for one expected "
                                         "turnaround; only conflicting, planned, a few free and spare gates listed"),
    "holding_fuel_available_min": (Basis.DATA, f"{wb.SRC}: fuel on arrival {SPARE_FUEL_ON_ARRIVAL_MIN} min of holding "
                                               f"minus the {FINAL_RESERVE_MIN}-min final reserve (conservative "
                                               "reading, see workbook.DEVIATIONS)"),
    "crew_fdp_end_min": (Basis.REGULATORY, f"{wb.SRC}: max duty from report time; crew assumed to follow the aircraft "
                                           "(report 1 h before its first departure in the file), with a fresh crew "
                                           "wherever the schedule itself would exceed the limit"),
    "crew_shift_end": (Basis.DATA, f"{wb.SRC}: {GROUND_SHIFT_H:g}-hour ground shifts; starts at "
                                   f"{', '.join(f'{h:02d}:00' for h in GROUND_SHIFT_STARTS_H)} (ASSUMPTION)"),
    "ground_shift_end_min": (Basis.DATA, "Same as crew_shift_end, in minutes after the DOT date's midnight"),
    "next_departure": (Basis.DATA, "Next leg of the same TAIL_NUMBER on the same day in flights.csv"),
    "min_turnaround_min": (Basis.DATA, f"{wb.SRC}, airport_capacity: min_turnaround_min at destination (the limit)"),
    "expected_turnaround_min": (Basis.DATA, f"Forecast: {TURNAROUND_SOURCE}, never below the workbook limit"),
}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _clock(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}" + ("+1" if minutes >= 1440 else "")


def scheduled_arrival_min(s: Disruption) -> int:
    return _minutes(s.scheduled_arrival) + 1440 * s.overnight


def scheduled_departure_min(s: Disruption) -> int:
    return _minutes(s.scheduled_departure)


def wake_category(s: Disruption) -> str:
    if s.aircraft_type:
        return category_from_model(s.aircraft_type)
    return heuristic_category(s.airline, s.distance_nm / 0.868976)


def expected_turnaround(airline: str, airport_code: str) -> int:
    """Forecast turnaround: the airline's calibrated median, never below the airport's workbook minimum."""
    return max(turnaround_min(airline), wb.airport(airport_code).min_turnaround_min)


def ground_shift_end(arrival_min: int) -> int:
    """End of the ground shift in which this arrival falls (minutes after the DOT date's midnight)."""
    day, t = divmod(arrival_min, 1440)
    starts = [h * 60 for h in GROUND_SHIFT_STARTS_H]
    start = max((x for x in starts if x <= t), default=starts[-1] - 1440)
    return day * 1440 + start + int(GROUND_SHIFT_H * 60)


def build_context(s: Disruption, bank: list[Arrival] = (), n_runways: int | None = None,
                  next_departure: str | None = None, crew_fdp_end_min: int | None = None,
                  airline_share: float | None = None) -> OpsContext:
    dest = wb.airport(s.destination)
    n_runways = n_runways or dest.active_runways
    runways = [f"R{i + 1}" for i in range(n_runways)]
    weather = s.cause == "WEATHER"
    closed = runways[:1] if weather and n_runways > 1 else []
    open_rwys = [r for r in runways if r not in closed]
    sched = scheduled_arrival_min(s)
    own = Arrival(s.flight_id, s.airline, sched + s.known_departure_delay_min, wake_category(s))
    interval = arrival_interval_min(dest.max_runway_ops_per_hour, n_runways, weather)
    slots, landed = sequence(list(bank), own, sched, open_rwys, interval)

    n_gates = GATES_PER_AIRLINE or max(1, round(dest.gates * (airline_share or DEFAULT_AIRLINE_SHARE)))
    airline_gates = [f"G{i + 1}" for i in range(n_gates)]
    planned = airline_gates[zlib.crc32(s.flight_id.encode()) % n_gates]
    turn = expected_turnaround(s.airline, s.destination)
    busy = gate_occupancy(landed, s.airline, airline_gates, turn)
    shown = {g: b for g, b in busy.items() if b > own.ready_min or g == planned}
    shown |= {g: 0 for g in [g for g in airline_gates if busy[g] == 0 and g not in shown][:FREE_GATES_SHOWN]}
    shown |= {f"SPARE{j + 1}": 0 for j in range(dest.spare_gates)}  # workbook: spare gates free at any time

    curfew = CURFEWS.get(s.destination)
    shift_end = ground_shift_end(sched)
    return OpsContext(
        wake_category=own.category,
        airport_class=dest.size_class,
        runways=runways,
        closed_runways=closed,
        arrival_interval_min=round(interval, 2),
        runway_slots=slots,
        earliest_arrival_delay_min=min(x.earliest_delay_min for x in slots.values()),
        ready_arrival_delay_min=s.known_departure_delay_min,
        decision_min=scheduled_departure_min(s) + s.known_departure_delay_min,
        curfew=curfew and f"{curfew[0] // 60:02d}:{curfew[0] % 60:02d}-{curfew[1] // 60:02d}:{curfew[1] % 60:02d}",
        gates=sorted(shown, key=lambda g: (g.startswith("SPARE"), len(g), g)),
        planned_gate=planned,
        gates_busy_until_min=shown,
        holding_fuel_available_min=SPARE_FUEL_ON_ARRIVAL_MIN - FINAL_RESERVE_MIN,
        crew_fdp_end_min=crew_fdp_end_min,
        crew_shift_end=_clock(shift_end),
        ground_shift_end_min=shift_end,
        next_departure=next_departure,
        min_turnaround_min=dest.min_turnaround_min,
        expected_turnaround_min=turn,
    )
