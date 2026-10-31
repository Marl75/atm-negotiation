"""Load the DOT 2015 flights file, pick disruption rows (WEATHER_DELAY > 15 or LATE_AIRCRAFT_DELAY > 20),
and derive what is known before departure: inbound delay, aircraft type, arrival bank, crew duty limit."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .aircraft import category_from_model, heuristic_category, tail_types
from .config import DATA_DIR
from .context import MIN_TURNAROUND_MIN, build_context
from .protocol import Disruption, OpsContext
from .rules import REPORT_BEFORE_FIRST_DEP_MIN, max_fdp_hours
from .traffic import Arrival

USECOLS = [
    "YEAR", "MONTH", "DAY", "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER",
    "ORIGIN_AIRPORT", "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE", "SCHEDULED_ARRIVAL",
    "DISTANCE", "WEATHER_DELAY", "LATE_AIRCRAFT_DELAY", "AIR_SYSTEM_DELAY",
    # Realised outcomes: evaluation baseline, and previous-leg arrival (known before our departure).
    # Never passed to the agents for the flight itself (not in Disruption).
    "ARRIVAL_DELAY", "DEPARTURE_DELAY",
]
BANK_WINDOW_MIN = 180  # arrivals ready up to 3 h before ours can still be queued ahead of it
DAY = ["YEAR", "MONTH", "DAY"]
TAIL_DAY = ["TAIL_NUMBER", *DAY]


def flights_path() -> Path:
    for name in ("flights.csv", "flights.csv.zip"):
        p = DATA_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError(f"Put the Challenge #2 DATA files (flights.csv, airlines.csv, airports.csv) in {DATA_DIR}")


def load_flights(nrows: int | None = None) -> pd.DataFrame:
    return enrich(pd.read_csv(flights_path(), usecols=USECOLS, nrows=nrows, low_memory=False))


def _hhmm_min(v: pd.Series) -> pd.Series:
    return v // 100 * 60 + v % 100


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add the ex-ante columns. Times are minutes after midnight of the DOT date (departure date)."""
    df = df.reset_index(drop=True)
    df["DEP_MIN"] = _hhmm_min(df["SCHEDULED_DEPARTURE"])
    df["ARR_MIN"] = _hhmm_min(df["SCHEDULED_ARRIVAL"]) + 1440 * (df["SCHEDULED_ARRIVAL"] < df["SCHEDULED_DEPARTURE"])

    # Inbound delay known before departure: previous leg of the same tail into our origin, landed late + turnaround
    left = df[df["TAIL_NUMBER"].notna()].reset_index()[["index", *TAIL_DAY, "ORIGIN_AIRPORT", "DEP_MIN"]]
    prev = df[df["TAIL_NUMBER"].notna()][[*TAIL_DAY, "DESTINATION_AIRPORT", "ARR_MIN", "ARRIVAL_DELAY",
                                          "AIRLINE", "FLIGHT_NUMBER"]]
    prev = prev.rename(columns={"DESTINATION_AIRPORT": "ORIGIN_AIRPORT", "ARR_MIN": "P_ARR", "ARRIVAL_DELAY": "P_DELAY",
                                "AIRLINE": "P_AL", "FLIGHT_NUMBER": "P_FN"})
    m = left.merge(prev, on=[*TAIL_DAY, "ORIGIN_AIRPORT"])
    m = m[m["P_ARR"] < m["DEP_MIN"]].sort_values("P_ARR").groupby("index").tail(1).set_index("index")
    from_prev = (m["P_ARR"] + m["P_DELAY"] + MIN_TURNAROUND_MIN - m["DEP_MIN"]).clip(lower=0)
    df["KNOWN_DEP_DELAY"] = from_prev.reindex(df.index).fillna(df["LATE_AIRCRAFT_DELAY"]).fillna(0).astype(int)
    df["KNOWN_DELAY_SRC"] = "LATE_AIRCRAFT_DELAY of the row (proxy for the inbound ETA; previous leg not in the file)"
    df.loc[m.index, "KNOWN_DELAY_SRC"] = ("previous leg " + m["P_AL"] + m["P_FN"].astype(str) + " landed "
                                          + m["P_DELAY"].astype(int).astype(str) + " min late, + "
                                          + str(MIN_TURNAROUND_MIN) + " min turnaround")
    df["READY_ARR"] = df["ARR_MIN"] + df["KNOWN_DEP_DELAY"]

    types = tail_types(frozenset(df["TAIL_NUMBER"].dropna().unique()))
    df["AIRCRAFT_TYPE"] = df["TAIL_NUMBER"].map(types)
    heuristic = [heuristic_category(a, d) for a, d in zip(df["AIRLINE"], df["DISTANCE"])]
    df["WAKE_CAT"] = df["AIRCRAFT_TYPE"].map(category_from_model, na_action="ignore").fillna(pd.Series(heuristic))

    df["DEST_ROWS"] = df.groupby("DESTINATION_AIRPORT")["DESTINATION_AIRPORT"].transform("size")
    return df


def disruptions(df: pd.DataFrame) -> pd.DataFrame:
    mask = (df["WEATHER_DELAY"] > 15) | (df["LATE_AIRCRAFT_DELAY"] > 20)
    return df[mask].reset_index(drop=True)


def load_disruptions(nrows: int | None = None) -> pd.DataFrame:
    return disruptions(load_flights(nrows))


def next_leg(df_all: pd.DataFrame, row: pd.Series) -> pd.Series | None:
    """Next leg of the same aircraft that day, from the destination airport.

    The provided file only keeps disrupted flights, so the next leg is missing whenever it was on time.
    """
    if not isinstance(row["TAIL_NUMBER"], str):
        return None
    same = df_all[(df_all["TAIL_NUMBER"] == row["TAIL_NUMBER"]) & (df_all["YEAR"] == row["YEAR"])
                  & (df_all["MONTH"] == row["MONTH"]) & (df_all["DAY"] == row["DAY"])
                  & (df_all["ORIGIN_AIRPORT"] == row["DESTINATION_AIRPORT"])
                  & (df_all["SCHEDULED_DEPARTURE"] > row["SCHEDULED_ARRIVAL"])]
    if same.empty:
        return None
    return same.sort_values("SCHEDULED_DEPARTURE").iloc[0]


def next_departure_same_tail(df_all: pd.DataFrame, row: pd.Series) -> str | None:
    leg = next_leg(df_all, row)
    return None if leg is None else _hhmm(leg["SCHEDULED_DEPARTURE"])


def _hhmm(v) -> str:
    v = int(v)
    return f"{v // 100:02d}:{v % 100:02d}"


def _flight_id(row) -> str:
    return f"{row['AIRLINE']}{row['FLIGHT_NUMBER']}-{row['YEAR']}{row['MONTH']:02d}{row['DAY']:02d}"


def row_to_disruption(row: pd.Series) -> Disruption:
    tail = row["TAIL_NUMBER"] if isinstance(row["TAIL_NUMBER"], str) else None
    return Disruption(
        flight_id=_flight_id(row),
        airline=row["AIRLINE"],
        flight_number=int(row["FLIGHT_NUMBER"]),
        tail_number=tail,
        aircraft_type=row["AIRCRAFT_TYPE"] if isinstance(row["AIRCRAFT_TYPE"], str) else None,
        origin=str(row["ORIGIN_AIRPORT"]),
        destination=str(row["DESTINATION_AIRPORT"]),
        scheduled_departure=_hhmm(row["SCHEDULED_DEPARTURE"]),
        scheduled_arrival=_hhmm(row["SCHEDULED_ARRIVAL"]),
        overnight=bool(row["ARR_MIN"] >= 1440),
        distance_nm=round(float(row["DISTANCE"]) * 0.868976, 1),  # DOT distance is statute miles
        known_departure_delay_min=int(row["KNOWN_DEP_DELAY"]),
        known_delay_source=row["KNOWN_DELAY_SRC"],
        # Scenario type only: the cause minutes themselves are attributed after the flight
        cause="WEATHER" if float(row["WEATHER_DELAY"] or 0) > 15 else "LATE_AIRCRAFT",
    )


def arrival_bank(df_all: pd.DataFrame, row: pd.Series) -> list[Arrival]:
    """Other arrivals at our destination that day, ready in the 3 h before us (from the disrupted-flights file)."""
    d = df_all[(df_all["YEAR"] == row["YEAR"]) & (df_all["MONTH"] == row["MONTH"]) & (df_all["DAY"] == row["DAY"])
               & (df_all["DESTINATION_AIRPORT"] == row["DESTINATION_AIRPORT"])
               & df_all["READY_ARR"].between(row["READY_ARR"] - BANK_WINDOW_MIN, row["READY_ARR"])]
    own = _flight_id(row)
    return [Arrival(fid, r["AIRLINE"], int(r["READY_ARR"]), r["WAKE_CAT"])
            for fid, (_, r) in zip(d.apply(_flight_id, axis=1), d.iterrows()) if fid != own]


def n_runways(dest_rows: int) -> int:
    return 3 if dest_rows > 8000 else 2 if dest_rows > 1000 else 1


def crew_fdp_end(df_all: pd.DataFrame, row: pd.Series) -> int | None:
    """End of the flight duty period of the crew flying this leg, minutes after midnight.

    The crew is assumed to follow the aircraft, except where the schedule itself would break Part 117:
    airlines schedule legally, so that leg starts with a fresh crew.
    """
    if not isinstance(row["TAIL_NUMBER"], str):
        return None
    legs = df_all[(df_all["TAIL_NUMBER"] == row["TAIL_NUMBER"]) & (df_all["YEAR"] == row["YEAR"])
                  & (df_all["MONTH"] == row["MONTH"]) & (df_all["DAY"] == row["DAY"])
                  & (df_all["DEP_MIN"] <= row["DEP_MIN"])].sort_values("DEP_MIN")
    deps, arrs = legs["DEP_MIN"].tolist(), legs["ARR_MIN"].tolist()
    start, end = 0, 0
    for j in range(len(deps)):
        report = int(deps[start]) - REPORT_BEFORE_FIRST_DEP_MIN
        end = report + int(max_fdp_hours(report, j - start + 1) * 60)
        if arrs[j] > end:  # scheduled arrival already beyond the limit: crew change before this leg
            start, report = j, int(deps[j]) - REPORT_BEFORE_FIRST_DEP_MIN
            end = report + int(max_fdp_hours(report, 1) * 60)
    return end


def build_scenario(df_all: pd.DataFrame, row: pd.Series) -> tuple[Disruption, OpsContext]:
    s = row_to_disruption(row)
    return s, build_context(s, arrival_bank(df_all, row), n_runways(int(row["DEST_ROWS"])),
                            next_departure_same_tail(df_all, row), crew_fdp_end(df_all, row))
