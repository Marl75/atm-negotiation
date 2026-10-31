"""Deterministic, non-AI resolution used when agents don't converge within MAX_ROUNDS."""

from __future__ import annotations

from .constraints import check_all
from .protocol import Disruption, Proposal


def deterministic_resolution(s: Disruption) -> Proposal | None:
    """Smallest delay that passes every hard constraint. TODO: real runway/gate candidates."""
    base = int(s.weather_delay_min + s.late_aircraft_delay_min)
    for extra in range(0, 121, 5):
        for holding in (0, 10, 20, 30):
            p = Proposal(revised_arrival_delay_min=base + extra, holding_min=holding,
                         runway="DEFAULT", gate="DEFAULT", rationale="deterministic fallback")
            if all(c.passed for c in check_all(s, p)):
                return p
    return None  # no safe option -> escalate to a human
