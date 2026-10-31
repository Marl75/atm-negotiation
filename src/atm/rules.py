"""Published rules and their sources (US airspace, US carriers). Values and table lookups only, no decision logic."""

from __future__ import annotations

# --- Fuel --------------------------------------------------------------------

# 14 CFR 121.639 (US domestic): fuel to destination, then alternate, then 45 min at normal cruise.
FINAL_RESERVE_MIN = 45
FINAL_RESERVE_SRC = "14 CFR 121.639 - US domestic fuel: destination + alternate + 45 min (ICAO/EASA: 30 min)"

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
WAKE_SRC = ("FAA JO 7110.65 para 5-5-4 wake minima on final (edition to verify; "
            "airports on wake RECAT use other values); 3 NM radar minimum otherwise")

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
FDP_SRC = ("14 CFR 117.13 Table B (unaugmented FDP); 117.19 allows up to +2 h after takeoff for unforeseen "
           "circumstances, with PIC and carrier agreement - beyond that, a fresh crew")
REPORT_BEFORE_FIRST_DEP_MIN = 60  # ASSUMPTION: crew reports 1 h before the first departure of the aircraft


def max_fdp_hours(report_min: int, segments: int) -> float:
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
