from ..constraints import check_atc, check_ground, check_pilot
from ..protocol import Role
from ..rules import (CREW_MAX_DUTY_H, FINAL_APPROACH_SPEED_KT, FINAL_RESERVE_MIN, GATE_CHANGE_NOTICE_MIN,
                     OVERTIME_FACTOR)
from .base import Agent


class ATCAgent(Agent):
    role = Role.ATC
    speaks_for = "the destination approach control (TRACON) and its traffic management unit"
    context_fields = ("runways", "closed_runways", "runway_slots", "earliest_arrival_delay_min", "wake_category",
                      "curfew")
    checks = check_atc
    objectives = (
        "- HARD: land on an open runway only (runway_open).\n"
        "- HARD: FAA JO 7110.65 wake separation behind this runway's leader, gap in minutes converted at "
        f"{FINAL_APPROACH_SPEED_KT} kt (wake_separation).\n"
        "- HARD: no landing before this flight's first-come-first-served slot on that runway (landing_slot_available).\n"
        "- HARD: no arrival inside the destination's noise curfew, if any (airport_curfew).\n"
        "- SOFT: maximise throughput, so keep the slot gap no larger than separation requires.\n"
        "- Your levers: runway, slot_gap_min, revised_arrival_delay_min."
    )


class PilotAgent(Agent):
    role = Role.PILOT
    speaks_for = "the flight crew and the airline's dispatch / operations control centre"
    context_fields = ("holding_fuel_available_min", "ready_arrival_delay_min", "crew_fdp_end_min", "wake_category")
    checks = check_pilot
    objectives = (
        f"- HARD: never plan below the {FINAL_RESERVE_MIN}-min final fuel reserve (challenge workbook): "
        "holding_min must not exceed the fuel available above it (final_reserve_fuel).\n"
        "- HARD: the aircraft cannot leave before it is ready: delay - holding >= ready_arrival_delay_min "
        "(departure_feasible).\n"
        f"- HARD: the crew must block in within {CREW_MAX_DUTY_H:g} h of report time (workbook, simplified FAA Part "
        "117) (flight_crew_duty). If impossible, say a human must decide (reserve crew).\n"
        "- SOFT: airborne holding costs ~4-5x a ground minute (fuel, CO2): take the wait on the ground at the "
        "origin before departure (holding_min = 0) whenever the slot is known in advance.\n"
        "- SOFT: protect passengers' connections, minimise turbulence exposure.\n"
        "- Your levers: holding_min, reroute."
    )


class GroundAgent(Agent):
    role = Role.GROUND
    speaks_for = "the airline's ground operations at the destination (gates, ramp crews)"
    context_fields = ("gates", "planned_gate", "gates_busy_until_min", "crew_shift_end", "next_departure",
                      "min_turnaround_min", "expected_turnaround_min")
    checks = check_ground
    objectives = (
        "- HARD: assign a gate that is free at the arrival time (gate_available; busy-until times are minutes "
        "after midnight).\n"
        f"- HARD: a gate change must be decided at least {GATE_CHANGE_NOTICE_MIN} min before arrival "
        "(gate_change_notice). SPARE gates are free at any time.\n"
        f"- SOFT: turnaround work done before the 8-hour ground shift ends; overtime costs {OVERTIME_FACTOR:g}x "
        "(crew_shift).\n"
        "- SOFT: leave the minimum turnaround before the next leg of the same aircraft (turnaround_next_leg).\n"
        "- Your levers: gate. You may ask for an earlier arrival in `concerns`, but not change runway or holding."
    )
