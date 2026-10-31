"""Offline tests (no API call): protocol, constraints, fallback."""

from atm.constraints import check_all
from atm.fallback import deterministic_resolution
from atm.protocol import Disruption, Proposal

S = Disruption(
    flight_id="AA100-20150101", airline="AA", flight_number=100, tail_number="N123AA",
    origin="ORD", destination="DFW", scheduled_departure="08:00", scheduled_arrival="10:30",
    distance_nm=700.0, weather_delay_min=25, late_aircraft_delay_min=0, air_system_delay_min=5,
    cause="WEATHER",
)


def test_fuel_reserve_violation_is_caught():
    p = Proposal(revised_arrival_delay_min=30, holding_min=50, runway="17C", gate="C3", rationale="t")
    failed = {c.constraint for c in check_all(S, p) if not c.passed}
    assert "final_reserve_fuel" in failed and "max_holding" in failed


def test_fallback_returns_safe_proposal():
    p = deterministic_resolution(S)
    assert p is not None and all(c.passed for c in check_all(S, p))
