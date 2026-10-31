"""Arrival bank at the destination: first-come-first-served sequencing of the flights ready before ours.

Pure functions, no data loading: data.py extracts the bank from flights.csv, context.py calls these.
Times are minutes after midnight of the DOT date.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .protocol import RunwaySlot
from .rules import separation_min

# ASSUMPTION: flights.csv only holds delayed flights, but on-time arrivals still use the runways. They load each
# runway at 70% in normal operations (in runway-equivalents, so closing a runway does not make them disappear).
# To calibrate with FAA ASPM arrival rates.
BACKGROUND_LOAD = 0.7
MIN_BANK_SHARE = 0.15  # ASSUMPTION: when saturated, flow control still releases 15% of capacity to the bank
WEATHER_SINGLE_RUNWAY_FACTOR = 1.5  # ASSUMPTION: one-runway airport in bad weather, spacing x1.5 (IMC)


@dataclass(frozen=True)
class Arrival:
    flight_id: str
    airline: str
    ready_min: int  # scheduled arrival + delay known before departure
    category: str   # FAA wake category


def spacing_factor(n_runways: int, n_open: int, weather: bool) -> float:
    """How much wider than wake separation the bank's arrivals are spaced, given the background traffic."""
    capacity = n_open / (WEATHER_SINGLE_RUNWAY_FACTOR if weather and n_runways == 1 else 1)
    free = max(MIN_BANK_SHARE * capacity, capacity - BACKGROUND_LOAD * n_runways)
    return n_open / free


def _earliest(last: tuple[int, str, str] | None, a: Arrival, factor: float) -> int:
    if last is None:
        return a.ready_min
    t, cat, _ = last
    return max(a.ready_min, math.ceil(t + separation_min(cat, a.category) * factor))


def sequence(bank: list[Arrival], own: Arrival, scheduled_min: int, runways: list[str],
             factor: float) -> tuple[dict[str, RunwaySlot], list[tuple[Arrival, int]]]:
    """Land every bank flight ready before ours on its earliest runway, then give ours its slot on each runway.

    Slots are returned as delay after our scheduled arrival.
    """
    last: dict[str, tuple[int, str, str] | None] = {r: None for r in runways}
    landed = []
    for a in sorted(bank, key=lambda a: (a.ready_min, a.flight_id)):
        if (a.ready_min, a.flight_id) >= (own.ready_min, own.flight_id):
            break
        rwy, t = min(((r, _earliest(last[r], a, factor)) for r in runways), key=lambda x: x[1])
        last[rwy] = (t, a.category, a.flight_id)
        landed.append((a, t))
    slots = {r: RunwaySlot(earliest_delay_min=_earliest(last[r], own, factor) - scheduled_min,
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
