"""Deterministic, non-AI resolution used when agents don't converge within MAX_ROUNDS."""

from __future__ import annotations

import math

from .constraints import FINAL_APPROACH_SPEED_KT, RADAR_MIN_NM, WAKE_MIN_NM, check_all, hard_ok
from .protocol import Disruption, OpsContext, Proposal


def deterministic_resolution(s: Disruption, c: OpsContext) -> Proposal | None:
    """Smallest delay that passes every hard constraint, preferring options that also pass the soft ones."""
    required_nm = WAKE_MIN_NM.get((c.leader_wake_category, c.wake_category), RADAR_MIN_NM)
    gap_min = math.ceil(required_nm * 600 / FINAL_APPROACH_SPEED_KT) / 10  # round up: never below the minimum
    best_hard_only = None
    for extra in range(0, 181, 5):
        for runway in c.runways:
            for gate in c.gates:
                p = Proposal(revised_arrival_delay_min=c.earliest_arrival_delay_min + extra, holding_min=0,
                             slot_gap_min=gap_min, runway=runway, gate=gate,
                             rationale="deterministic fallback: earliest slot passing all hard constraints")
                results = check_all(s, c, p)
                if not hard_ok(results):
                    continue
                if all(r.passed for r in results):
                    return p
                best_hard_only = best_hard_only or p
    return best_hard_only  # None -> no safe option, escalate to a human
