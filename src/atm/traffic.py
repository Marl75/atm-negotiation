"""Arrival bank at the destination: first-come-first-served sequencing of the flights ready before ours.

Pure functions, no data loading: data.py extracts the bank from flights.csv, context.py calls these.
Times are minutes after midnight of the DOT date.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .protocol import RunwaySlot
from .rules import separation_min

# Capacity from the challenge workbook (max_runway_ops_per_hour, active_runways), synthetic limits scaled from the
# traffic in flights.csv. ASSUMPTION: half of the runway movements are arrivals.
ARRIVAL_SHARE = 0.5
WEATHER_SINGLE_RUNWAY_FACTOR = 1.5  # ASSUMPTION: one-runway airport in bad weather, spacing x1.5 (IMC)


@dataclass(frozen=True)
class Arrival:
    flight_id: str
    airline: str
    ready_min: int  # scheduled arrival + delay known before departure
    category: str   # FAA wake category


def arrival_interval_min(max_ops_per_hour: int, n_runways: int, weather: bool) -> float:
    """Minimum minutes between two arrivals on one runway at the workbook's capacity.

    Per-runway capacity is fixed: closing a runway removes its share (the airport's arrival rate drops).
    """
    per_runway_per_hour = ARRIVAL_SHARE * max_ops_per_hour / n_runways
    return 60 / per_runway_per_hour * (WEATHER_SINGLE_RUNWAY_FACTOR if weather and n_runways == 1 else 1)


def _earliest(last: tuple[int, str, str] | None, a: Arrival, interval: float) -> int:
    if last is None:
        return a.ready_min
    t, cat, _ = last
    return max(a.ready_min, math.ceil(t + max(separation_min(cat, a.category), interval)))


def sequence(bank: list[Arrival], own: Arrival, scheduled_min: int, runways: list[str],
             interval: float) -> tuple[dict[str, RunwaySlot], list[tuple[Arrival, int]]]:
    """Land every bank flight ready before ours on its earliest runway, then give ours its slot on each runway.

    Slots are returned as delay after our scheduled arrival.
    """
    last: dict[str, tuple[int, str, str] | None] = {r: None for r in runways}
    landed = []
    for a in sorted(bank, key=lambda a: (a.ready_min, a.flight_id)):
        if (a.ready_min, a.flight_id) >= (own.ready_min, own.flight_id):
            break
        rwy, t = min(((r, _earliest(last[r], a, interval)) for r in runways), key=lambda x: x[1])
        last[rwy] = (t, a.category, a.flight_id)
        landed.append((a, t))
    slots = {r: RunwaySlot(earliest_delay_min=_earliest(last[r], own, interval) - scheduled_min,
                           leader_category=last[r][1] if last[r] else None,
                           leader_flight=last[r][2] if last[r] else None) for r in runways}
    return slots, landed


def gate_occupancy(landed: list[tuple[Arrival, int]], airline: str, gates: list[str],
                   turnaround_min: int) -> dict[str, int]:
    """Same-airline arrivals ahead of ours take the first free gate for one turnaround. Returns busy-until per gate."""
    busy = {g: 0 for g in gates}
    for a, t in sorted(((a, t) for a, t in landed if a.airline == airline), key=lambda x: x[1]):
        g = min(gates, key=lambda g: (busy[g] > t, busy[g]))  # a free gate first, else the one freed soonest
        busy[g] = max(t, busy[g]) + turnaround_min
    return busy
