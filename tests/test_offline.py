"""Offline tests (no API call): protocol, constraints, fallback."""

from atm.constraints import check_all, hard_ok
from atm.context import PROVENANCE, build_context
from atm.fallback import deterministic_resolution
from atm.protocol import Basis, Disruption, OpsContext, Proposal

S = Disruption(
    flight_id="AA100-20150101", airline="AA", flight_number=100, tail_number="N123AA",
    origin="ORD", destination="DFW", scheduled_departure="08:00", scheduled_arrival="10:30",
    distance_nm=700.0, weather_delay_min=25, late_aircraft_delay_min=0, air_system_delay_min=5,
    cause="WEATHER",
)
C = build_context(S, next_departure="11:30")


def _p(**kw) -> Proposal:
    base = dict(revised_arrival_delay_min=25, holding_min=0, slot_gap_min=2.5, runway="R2", gate="G2", rationale="t")
    return Proposal(**(base | kw))


def failed(p: Proposal) -> set[str]:
    return {r.constraint for r in check_all(S, C, p) if not r.passed}


def test_every_context_field_has_provenance():
    assert set(PROVENANCE) == set(OpsContext.model_fields)


def test_every_check_is_sourced():
    assert all(r.source and r.basis in Basis for r in check_all(S, C, _p()))


def test_safe_proposal_passes_hard_checks():
    assert hard_ok(check_all(S, C, _p()))


def test_fuel_reserve_violation_is_caught():
    assert "final_reserve_fuel" in failed(_p(holding_min=30))


def test_wake_separation_medium_behind_heavy():
    # 1.5 min at 140 kt = 3.5 NM < 5 NM required for M behind H
    assert "wake_separation" in failed(_p(slot_gap_min=1.5))


def test_closed_runway_and_early_slot_are_caught():
    assert {"runway_open", "landing_slot_available"} <= failed(_p(runway="R1", revised_arrival_delay_min=10))


def test_turnaround_is_soft():
    results = check_all(S, C, _p(revised_arrival_delay_min=60))
    turn = next(r for r in results if r.constraint == "turnaround_next_leg")
    assert not turn.passed and not turn.hard and hard_ok(results)


def test_fallback_returns_safe_proposal():
    p = deterministic_resolution(S, C)
    assert p is not None and hard_ok(check_all(S, C, p))
