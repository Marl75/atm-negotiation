"""Published rules and their sources (US airspace, US carriers). Values and table lookups only, no decision logic."""

from __future__ import annotations

# --- Fuel --------------------------------------------------------------------

from . import workbook as wb

# Challenge workbook, fuel_and_crew sheet. (Real-world reference: 14 CFR 121.639, alternate + 45 min.)
FINAL_RESERVE_MIN = int(wb.rule_numbers("Final fuel reserve")[0])                 # 30
SPARE_FUEL_ON_ARRIVAL_MIN = int(wb.rule_numbers("Assumed spare fuel on arrival")[0])  # 45, total holding fuel
FINAL_RESERVE_SRC = (f"{wb.SRC}: final reserve {FINAL_RESERVE_MIN} min of holding fuel, never planned below; "
                     f"assumed fuel on arrival {SPARE_FUEL_ON_ARRIVAL_MIN} min of holding")
HOLDING_BURN_KG_PER_H = {"narrowbody": wb.rule_numbers("Holding fuel burn (narrowbody)")[0],   # 2400
                         "widebody": wb.rule_numbers("Holding fuel burn (widebody)")[0]}       # 6500


def holding_burn_kg_per_min(wake_category: str) -> float:
    return HOLDING_BURN_KG_PER_H["widebody" if wake_category in ("HEAVY", "SUPER") else "narrowbody"] / 60


# Ground ops (workbook)
GROUND_SHIFT_H, OVERTIME_FACTOR = wb.rule_numbers("Ground crew shift")                # 8 h, 1.5x
GROUND_SHIFT_STARTS_H = (6, 14, 22)  # ASSUMPTION: three 8-hour shifts a day
GATE_CHANGE_NOTICE_MIN = int(wb.rule_numbers("Gate change notice")[0])                # 20
GROUND_SRC = f"{wb.SRC}: ground crew shift {GROUND_SHIFT_H:g} h, overtime {OVERTIME_FACTOR:g}x after that"
GATE_NOTICE_SRC = f"{wb.SRC}: gate change notice at least {GATE_CHANGE_NOTICE_MIN} min before arrival"

# --- Wake turbulence (FAA categories, not ICAO: the DOT data is US airspace) ---

CATEGORIES = ("SUPER", "HEAVY", "B757", "LARGE", "SMALL")

# FAA JO 7110.65 para 5-5-4, distance-based wake minima on final approach, NM, (leader, follower).
WAKE_MIN_NM = {
    ("SUPER", "HEAVY"): 6, ("SUPER", "B757"): 7, ("SUPER", "LARGE"): 7, ("SUPER", "SMALL"): 8,
    ("HEAVY", "HEAVY"): 4, ("HEAVY", "B757"): 5, ("HEAVY", "LARGE"): 5, ("HEAVY", "SMALL"): 6,
    ("B757", "SMALL"): 4,
    ("LARGE", "SMALL"): 4,
}
RADAR_MIN_NM = 3  # 7110.65 para 5-5-4: 3 NM radar minimum when no wake minimum applies
WAKE_SRC = (f"{wb.SRC}, wake_separation (simplified FAA JO 7110.65); FAA B757 category kept; "
            "3 NM for any other pair")

FINAL_APPROACH_SPEED_KT = 140  # ASSUMPTION: typical narrowbody final approach groundspeed


def required_nm(leader: str | None, follower: str) -> float:
    return WAKE_MIN_NM.get((leader, follower), RADAR_MIN_NM)


def separation_min(leader: str | None, follower: str) -> float:
    """Minutes behind the leader on final, at FINAL_APPROACH_SPEED_KT."""
    return required_nm(leader, follower) * 60 / FINAL_APPROACH_SPEED_KT


# --- Flight crew duty: 14 CFR Part 117 -----------------------------------------

# Table B, unaugmented operations: max flight duty period (hours) by scheduled report time (local, acclimated)
# and number of flight segments (1, 2, 3, 4, 5, 6, 7+).
FDP_TABLE_B = [
    (0, 4, (9, 9, 9, 9, 9, 9, 9)),
    (4, 5, (10, 10, 10, 10, 9, 9, 9)),
    (5, 6, (12, 12, 12, 12, 11.5, 11, 10.5)),
    (6, 7, (13, 13, 12, 12, 11.5, 11, 10.5)),
    (7, 12, (14, 14, 13, 13, 12.5, 12, 11.5)),
    (12, 13, (13, 13, 13, 13, 12.5, 12, 11.5)),
    (13, 17, (12, 12, 12, 12, 11.5, 11, 10.5)),
    (17, 22, (12, 12, 11, 11, 10, 9, 9)),
    (22, 23, (11, 11, 10, 10, 9, 9, 9)),
    (23, 24, (10, 10, 10, 9, 9, 9, 9)),
]
CREW_MAX_DUTY_H = wb.rule_numbers("Flight crew max duty")[0]  # 13 h from report time (workbook)
# "workbook" (default, rules of play) or "part117" (Table B above, as a sensitivity variant to state in the demo)
CREW_DUTY_MODEL = "workbook"
FDP_SRC = (f"{wb.SRC}: flight crew max duty {CREW_MAX_DUTY_H:g} h from report time (simplified FAA Part 117)")
FDP_SRC_PART117 = ("14 CFR 117.13 Table B (unaugmented FDP); 117.19 allows up to +2 h after takeoff for unforeseen "
                   "circumstances, with PIC and carrier agreement - beyond that, a fresh crew")
REPORT_BEFORE_FIRST_DEP_MIN = 60  # ASSUMPTION: crew reports 1 h before the first departure of the aircraft


def max_fdp_hours(report_min: int, segments: int) -> float:
    if CREW_DUTY_MODEL == "workbook":
        return CREW_MAX_DUTY_H
    hour = report_min // 60 % 24
    row = next(limits for start, end, limits in FDP_TABLE_B if start <= hour < end)
    return row[min(max(segments, 1), 7) - 1]


# --- Airport curfews -------------------------------------------------------------

# Airport -> (start, end) of the window with no commercial arrivals, local minutes, and source.
CURFEWS = {
    "SNA": (23 * 60, 7 * 60, "John Wayne Airport noise ordinance: commercial arrivals 07:00-23:00 (to verify)"),
    "LGB": (22 * 60, 7 * 60, "Long Beach Airport noise ordinance: commercial operations 07:00-22:00, "
                             "later operations penalised (to verify)"),
}


def in_curfew(airport: str, clock_min: int) -> bool:
    if airport not in CURFEWS:
        return False
    start, end, _ = CURFEWS[airport]
    t = clock_min % 1440
    return t >= start or t < end if start > end else start <= t < end
