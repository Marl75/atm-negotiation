"""Load the DOT 2015 flights file and pick disruption rows (WEATHER_DELAY > 15 or LATE_AIRCRAFT_DELAY > 20)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DATA_DIR
from .protocol import Disruption

USECOLS = [
    "YEAR", "MONTH", "DAY", "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER",
    "ORIGIN_AIRPORT", "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE", "SCHEDULED_ARRIVAL",
    "DISTANCE", "WEATHER_DELAY", "LATE_AIRCRAFT_DELAY", "AIR_SYSTEM_DELAY",
    # Realised outcomes: evaluation baseline only, never passed to the agents (not in Disruption)
    "ARRIVAL_DELAY", "DEPARTURE_DELAY",
]


def flights_path() -> Path:
    for name in ("flights.csv", "flights.csv.zip"):
        p = DATA_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError(f"Put the Challenge #2 DATA files (flights.csv, airlines.csv, airports.csv) in {DATA_DIR}")


def load_flights(nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(flights_path(), usecols=USECOLS, nrows=nrows, low_memory=False)


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


def row_to_disruption(row: pd.Series) -> Disruption:
    weather = float(row["WEATHER_DELAY"] or 0)
    return Disruption(
        flight_id=f"{row['AIRLINE']}{row['FLIGHT_NUMBER']}-{row['YEAR']}{row['MONTH']:02d}{row['DAY']:02d}",
        airline=row["AIRLINE"],
        flight_number=int(row["FLIGHT_NUMBER"]),
        tail_number=row["TAIL_NUMBER"] if isinstance(row["TAIL_NUMBER"], str) else None,
        origin=str(row["ORIGIN_AIRPORT"]),
        destination=str(row["DESTINATION_AIRPORT"]),
        scheduled_departure=_hhmm(row["SCHEDULED_DEPARTURE"]),
        scheduled_arrival=_hhmm(row["SCHEDULED_ARRIVAL"]),
        distance_nm=round(float(row["DISTANCE"]) * 0.868976, 1),  # DOT distance is statute miles
        weather_delay_min=weather,
        late_aircraft_delay_min=float(row["LATE_AIRCRAFT_DELAY"] or 0),
        air_system_delay_min=float(row["AIR_SYSTEM_DELAY"] or 0),
        cause="WEATHER" if weather > 15 else "LATE_AIRCRAFT",
    )
