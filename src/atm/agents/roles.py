from ..constraints import FINAL_APPROACH_SPEED_KT, FINAL_RESERVE_MIN, check_atc, check_ground, check_pilot
from ..protocol import Role
from .base import Agent


class ATCAgent(Agent):
    role = Role.ATC
    context_fields = ("runways", "closed_runways", "wake_category", "leader_wake_category",
                      "earliest_arrival_delay_min")
    checks = check_atc
    objectives = (
        "- HARD: land on an open runway only (runway_open).\n"
        "- HARD: wake separation behind the leader per ICAO Doc 4444, gap in minutes converted at "
        f"{FINAL_APPROACH_SPEED_KT} kt (wake_separation).\n"
        "- HARD: no landing before the earliest available slot (landing_slot_available).\n"
        "- SOFT: maximise sector throughput, so keep the slot gap no larger than separation requires.\n"
        "- Your levers: runway, slot_gap_min, revised_arrival_delay_min, holding_min."
    )


class PilotAgent(Agent):
    role = Role.PILOT
    context_fields = ("holding_fuel_available_min", "wake_category")
    checks = check_pilot
    objectives = (
        f"- HARD: never eat into the final reserve (alternate + {FINAL_RESERVE_MIN} min, 14 CFR 121.639): "
        "holding_min must not exceed the fuel available above it (final_reserve_fuel).\n"
        "- SOFT: airborne holding costs ~4-5x a ground minute, so prefer delay on the ground or a later slot "
        "over holding.\n"
        "- SOFT: protect passengers' connections, minimise turbulence exposure.\n"
        "- Your levers: holding_min, reroute."
    )


class GroundAgent(Agent):
    role = Role.GROUND
    context_fields = ("gates", "blocked_gates", "crew_shift_end", "next_departure", "min_turnaround_min")
    checks = check_ground
    objectives = (
        "- HARD: assign a gate that exists and is not blocked (gate_available).\n"
        "- SOFT: arrival before the ground-crew shift end, no overtime (crew_shift).\n"
        "- SOFT: leave the minimum turnaround before the next leg of the same aircraft (turnaround_next_leg).\n"
        "- Your levers: gate. You may ask for an earlier arrival in `concerns`, but not change runway or holding."
    )
