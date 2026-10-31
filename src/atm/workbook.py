"""The challenge's operational constraints workbook (challenge2_operational_constraints.xlsx), read once.

Rules of play: "Use the limits in this workbook. Any limit you change must be stated in your demo."
Airport values are SYNTHETIC planning limits scaled from each airport's traffic in flights.csv (not real airport
data). Every limit used by the checks comes from here, cited as WORKBOOK; deviations are listed in DEVIATIONS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from .config import ROOT

PATH = ROOT / "data" / "constraints" / "challenge2_operational_constraints.xlsx"
SRC = "challenge workbook (challenge2_operational_constraints.xlsx)"


@dataclass(frozen=True)
class AirportLimits:
    code: str
    size_class: str
    active_runways: int
    gates: int
    max_runway_ops_per_hour: int
    min_turnaround_min: int
    spare_gates: int


@lru_cache(maxsize=1)
def _book() -> dict:
    if not PATH.exists():
        raise FileNotFoundError(f"Challenge constraints workbook missing: {PATH}")
    x = pd.ExcelFile(PATH)
    a = pd.read_excel(x, "airport_capacity", header=2).dropna(subset=["IATA_CODE"])
    airports = {r.IATA_CODE: AirportLimits(r.IATA_CODE, r.size_class, int(r.active_runways), int(r.gates),
                                           int(r.max_runway_ops_per_hour), int(r.min_turnaround_min),
                                           int(r.spare_gates_at_any_time)) for r in a.itertuples()}
    w = pd.read_excel(x, "wake_separation", header=2)
    wake = {(str(r.leader), str(r.follower)): float(r.min_separation_nm) for r in w.itertuples()}
    f = pd.read_excel(x, "fuel_and_crew")
    rules = {str(r.rule): str(r.value) for r in f.itertuples()}
    return {"airports": airports, "wake": wake, "rules": rules}


def airport(code: str) -> AirportLimits:
    """Limits of an airport; an airport absent from the workbook gets the smallest class (Non-hub)."""
    ap = _book()["airports"]
    if code in ap:
        return ap[code]
    nonhub = next(v for v in ap.values() if v.size_class == "Non-hub")
    return AirportLimits(code, "Non-hub (not in workbook)", nonhub.active_runways, nonhub.gates,
                         nonhub.max_runway_ops_per_hour, nonhub.min_turnaround_min, nonhub.spare_gates)


def rule_numbers(name: str) -> list[float]:
    """Numbers in a fuel_and_crew value, e.g. '8 hours; overtime costs 1.5x after that' -> [8.0, 1.5]."""
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", _book()["rules"][name])]


def rule_text(name: str) -> str:
    return _book()["rules"][name]


def wake_table() -> dict[tuple[str, str], float]:
    return dict(_book()["wake"])


# Limits we deliberately changed or added, to state in the demo (rules of play)
DEVIATIONS = [
    "Turnaround forecast: aircraft-ready time uses the airline's median observed turnaround (calibrated on Jan-Jun "
    "2015, calibration.py), never below the workbook's minimum turnaround, which stays the limit.",
    "Wake: the FAA B757 category is kept (FAA JO 7110.65); the workbook pairs are identical otherwise.",
    "Curfews: airport noise curfews added (cited in rules.CURFEWS); not in the workbook.",
    "Fuel: 'assumed spare fuel on arrival 45 min' read as total holding fuel on arrival, so with the 30-min final "
    "reserve only 15 min can be spent holding (conservative reading).",
    "Runway ops per hour: half assumed to be arrivals (ARRIVAL_SHARE = 0.5).",
    "Ground crew shifts: 8 h (workbook) starting 06:00, 14:00, 22:00 (assumption).",
    "Airline gates: the airport's gates split by the airline's share of arrivals there in flights.csv.",
]
