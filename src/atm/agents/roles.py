from ..constraints import check_atc, check_ground, check_pilot
from ..protocol import Role
from ..rules import FINAL_APPROACH_SPEED_KT, FINAL_RESERVE_MIN
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
        f"- HARD: never eat into the final reserve (alternate + {FINAL_RESERVE_MIN} min, 14 CFR 121.639): "
        "holding_min must not exceed the fuel available above it (final_reserve_fuel).\n"
        "- HARD: the aircraft cannot leave before it is ready: delay - holding >= ready_arrival_delay_min "
        "(departure_feasible).\n"
        "- HARD: the crew must block in before the end of its 14 CFR 117 flight duty period (flight_crew_duty). "
        "If impossible, say a human must decide (117.19 extension or reserve crew).\n"
        "- SOFT: airborne holding costs ~4-5x a ground minute (fuel, CO2): take the wait on the ground at the "
        "origin before departure (holding_min = 0) whenever the slot is known in advance.\n"
        "- SOFT: protect passengers' connections, minimise turbulence exposure.\n"
        "- Your levers: holding_min, reroute."
    )


class GroundAgent(Agent):
    role = Role.GROUND
    speaks_for = "the airline's ground operations at the destination (gates, ramp crews)"
    context_fields = ("gates", "planned_gate", "gates_busy_until_min", "crew_shift_end", "next_departure",
                      "min_turnaround_min")
    checks = check_ground
    objectives = (
        "- HARD: assign a gate that is free at the arrival time (gate_available; busy-until times are minutes "
        "after midnight).\n"
        "- SOFT: arrival before the ground-crew shift end, no overtime (crew_shift).\n"
        "- SOFT: leave the minimum turnaround before the next leg of the same aircraft (turnaround_next_leg).\n"
        "- Your levers: gate. You may ask for an earlier arrival in `concerns`, but not change runway or holding."
    )
