"""The challenge workbook is the source of the limits (no API call)."""

from atm import rules, workbook as wb
from atm.constraints import check_all
from atm.context import build_context, expected_turnaround, ground_shift_end
from atm.negotiation import negotiate
from atm.protocol import Evaluation, Role
from test_offline import S, _p

NAMES = {"Super (A380)": "SUPER", "Heavy": "HEAVY", "Large": "LARGE", "Small": "SMALL"}


def test_wake_table_matches_workbook():
    for (leader, follower), nm in wb.wake_table().items():
        if leader == "Any other pair":
            assert rules.RADAR_MIN_NM == nm
        else:
            assert rules.required_nm(NAMES[leader], NAMES[follower]) == nm


def test_fuel_crew_ground_limits_come_from_workbook():
    assert rules.FINAL_RESERVE_MIN == 30 and rules.SPARE_FUEL_ON_ARRIVAL_MIN == 45
    assert rules.CREW_MAX_DUTY_H == 13 and rules.GATE_CHANGE_NOTICE_MIN == 20
    assert (rules.GROUND_SHIFT_H, rules.OVERTIME_FACTOR) == (8, 1.5)
    assert rules.holding_burn_kg_per_min("HEAVY") == 6500 / 60 and rules.holding_burn_kg_per_min("LARGE") == 40


def test_airport_capacity_drives_runways_gates_and_turnaround():
    c = build_context(S)  # DFW, large hub in the workbook
    dfw = wb.airport("DFW")
    assert len(c.runways) == dfw.active_runways == 4 and c.min_turnaround_min == dfw.min_turnaround_min == 45
    assert sum(g.startswith("SPARE") for g in c.gates) == dfw.spare_gates == 3
    assert c.holding_fuel_available_min == 15  # 45 min on arrival - 30 min reserve (conservative reading)
    assert wb.airport("ZZZ").size_class.startswith("Non-hub")


def test_expected_turnaround_never_below_workbook_limit():
    assert expected_turnaround("HA", "DFW") == 45  # HA median 27 < DFW limit 45
    assert expected_turnaround("UA", "DFW") == 54  # UA median 54 > limit


def test_ground_shift_and_overtime():
    assert ground_shift_end(10 * 60) == 14 * 60 and ground_shift_end(23 * 60) == 30 * 60
    assert ground_shift_end(2 * 60) == 6 * 60  # night shift started the evening before
    late = [r for r in check_all(S, build_context(S), _p(revised_arrival_delay_min=200)) if r.constraint == "crew_shift"]
    assert not late[0].passed and "1.5x" in late[0].detail


def test_gate_change_needs_notice():
    c = build_context(S)
    spare = next(g for g in c.gates if g.startswith("SPARE"))
    ok = [r for r in check_all(S, c, _p(gate=spare)) if r.constraint == "gate_change_notice"]
    assert ok and ok[0].passed and ok[0].hard  # decided at departure, hours before arrival
    late = c.model_copy(update={"decision_min": 10 * 60 + 30 + 25 - 10})  # decided 10 min before arrival
    bad = [r for r in check_all(S, late, _p(gate=spare)) if r.constraint == "gate_change_notice"]
    assert not bad[0].passed


class _RejectAll:
    def __init__(self, role): self.role = role
    def evaluate(self, s, c, p, history=""):
        return Evaluation(role=self.role, accept=False, violated_constraints=["x"])


def test_fallback_logs_why():
    out = negotiate(S, build_context(S, n_runways=2), _p(), [_RejectAll(r) for r in Role])
    assert out.resolved_by == "deterministic_fallback"
    assert "without any counter-proposal" in out.fallback_reason and "rejected by ATC (x)" in out.fallback_reason
