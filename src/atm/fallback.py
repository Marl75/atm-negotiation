"""Deterministic, non-AI resolution used when agents don't converge within MAX_ROUNDS."""

from __future__ import annotations

import math

from .constraints import check_all, hard_ok
from .protocol import Disruption, OpsContext, Proposal
from .rules import FINAL_APPROACH_SPEED_KT, required_nm


def min_gap(c: OpsContext, runway: str) -> float:
    """Wake gap behind this runway's leader in minutes, rounded up to 0.1: never below the minimum."""
    nm = required_nm(c.runway_slots[runway].leader_category, c.wake_category)
    return math.ceil(nm * 600 / FINAL_APPROACH_SPEED_KT) / 10


def deterministic_resolution(s: Disruption, c: OpsContext) -> Proposal | None:
    """Smallest delay that passes every hard constraint, preferring options that also pass the soft ones.

    No airborne holding: the whole delay is a ground hold at the origin (cheapest, safest place to wait).
    """
    best_hard_only = None
    for extra in range(0, 181, 5):
        for runway in c.runway_slots:
            for gate in c.gates:
                p = Proposal(revised_arrival_delay_min=c.earliest_arrival_delay_min + extra, holding_min=0,
                             slot_gap_min=min_gap(c, runway), runway=runway, gate=gate,
                             rationale="deterministic fallback: earliest slot passing all hard constraints, "
                                       "delay taken on the ground at origin")
                results = check_all(s, c, p)
                if not hard_ok(results):
                    continue
                if all(r.passed for r in results):
                    return p
                best_hard_only = best_hard_only or p
    return best_hard_only  # None -> no safe option, escalate to a human
