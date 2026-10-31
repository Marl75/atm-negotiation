"""Offline tests (no API call): protocol, rules, traffic model, constraints, fallback."""

from atm.aircraft import category_from_model
from atm.constraints import check_all, hard_ok
from atm.context import PROVENANCE, build_context
from atm.fallback import deterministic_resolution
from atm.negotiation import naive_initial, select_counter
from atm.protocol import Basis, Disruption, Evaluation, OpsContext, Proposal, Role
from atm.rules import max_fdp_hours, required_nm
from atm.traffic import Arrival, arrival_interval_min

S = Disruption(
    flight_id="AA100-20150101", airline="AA", flight_number=100, tail_number="N123AA",
    aircraft_type="BOEING 737-823", origin="ORD", destination="DFW", scheduled_departure="08:00",
    scheduled_arrival="10:30", distance_nm=700.0, known_departure_delay_min=25, known_delay_source="test",
    cause="WEATHER",
)
C = build_context(S, n_runways=2, next_departure="11:30")  # 2 runways, R1 closed by weather, no traffic: slot = ready = +25
SCHED = 10 * 60 + 30


def _p(**kw) -> Proposal:
    base = dict(revised_arrival_delay_min=25, holding_min=0, slot_gap_min=2.5, runway="R2", gate=C.planned_gate,
                rationale="t")
    return Proposal(**(base | kw))


def failed(p: Proposal, s: Disruption = S, c: OpsContext = C) -> set[str]:
    return {r.constraint for r in check_all(s, c, p) if not r.passed}


def test_every_context_field_has_provenance():
    assert set(PROVENANCE) == set(OpsContext.model_fields)


def test_agents_never_see_ex_post_delay_causes():
    assert not any(k in f for f in Disruption.model_fields for k in ("weather_delay", "late_aircraft", "air_system"))


def test_every_check_is_sourced():
    assert all(r.source and r.basis in Basis for r in check_all(S, C, _p()))


def test_safe_proposal_passes_hard_checks():
    assert hard_ok(check_all(S, C, _p()))


def test_faa_wake_rules_and_categories():
    assert required_nm("HEAVY", "LARGE") == 5 and required_nm(None, "LARGE") == 3 and required_nm("LARGE", "LARGE") == 3
    assert [category_from_model(m) for m in ("BOEING 757-232", "BOEING 767-332ER", "BOEING 737-7H4", "AIRBUS A380-861",
                                              "BOMBARDIER INC CL-600-2B19")] == ["B757", "HEAVY", "LARGE", "SUPER", "LARGE"]


def test_part_117_table_b(monkeypatch):
    from atm import rules

    assert max_fdp_hours(8 * 60, 9) == 13  # workbook default: 13 h from report time
    monkeypatch.setattr(rules, "CREW_DUTY_MODEL", "part117")  # sensitivity variant
    assert max_fdp_hours(6 * 60, 2) == 13 and max_fdp_hours(23 * 60 + 30, 5) == 9 and max_fdp_hours(8 * 60, 9) == 11.5


def test_fuel_reserve_violation_is_caught():
    assert "final_reserve_fuel" in failed(_p(revised_arrival_delay_min=55, holding_min=30))


def test_cannot_depart_before_aircraft_is_ready():
    # 25 min delay with 10 min holding means leaving 10 min before the inbound aircraft is ready
    assert "departure_feasible" in failed(_p(holding_min=10))


def _bank(*arrivals) -> list[Arrival]:
    return [Arrival(f"X{i}", al, SCHED + ready, cat) for i, (al, ready, cat) in enumerate(arrivals)]


def test_queue_ahead_pushes_slot_and_sets_leader():
    c = build_context(S, _bank(("UA", 20, "HEAVY"), ("DL", 22, "LARGE"), ("UA", 24, "HEAVY")), n_runways=2)
    slot = c.runway_slots["R2"]
    assert slot.earliest_delay_min > 25 and slot.leader_category == "HEAVY" and slot.leader_flight == "X2"
    # 1.5 min at 140 kt = 3.5 NM < 5 NM required for a LARGE behind a HEAVY
    assert "wake_separation" in failed(_p(revised_arrival_delay_min=slot.earliest_delay_min, slot_gap_min=1.5), c=c)
    assert "landing_slot_available" in failed(_p(), c=c)


def test_closing_a_runway_saturates_capacity():
    # workbook capacity per runway is fixed: one-runway weather spacing widens, and the interval follows ops/hour
    assert arrival_interval_min(36, 1, weather=True) == 1.5 * arrival_interval_min(36, 1, weather=False)
    assert arrival_interval_min(90, 4, weather=False) == 60 / (0.5 * 90 / 4)


def test_closed_runway_and_early_slot_are_caught():
    assert {"runway_open", "landing_slot_available"} <= failed(_p(runway="R1", revised_arrival_delay_min=10))


def test_status_quo_waits_in_the_air_and_can_fail_on_its_own(monkeypatch):
    from atm import context

    monkeypatch.setattr(context, "GATES_PER_AIRLINE", 1)  # one airline gate: the arrivals ahead hold it
    s = S.model_copy(update={"cause": "LATE_AIRCRAFT"})
    c = build_context(s, _bank(*[("AA", 20 + i, "LARGE") for i in range(6)]), n_runways=2)
    sq = naive_initial(s, c)
    assert sq.holding_min == sq.revised_arrival_delay_min - 25 > 0 and sq.gate == c.planned_gate
    assert "gate_available" in failed(sq, s, c)  # same-airline arrivals just ahead still hold the planned gate
    fb = deterministic_resolution(s, c)
    assert fb.holding_min == 0 and hard_ok(check_all(s, c, fb))


def test_crew_duty_limit_escalates_when_no_safe_option():
    c = build_context(S, crew_fdp_end_min=SCHED + 10)
    assert "flight_crew_duty" in failed(_p(), c=c)
    assert deterministic_resolution(S, c) is None  # no safe option: a human decides (117.19 or reserve crew)


def test_curfew_is_hard():
    s = S.model_copy(update={"destination": "SNA", "scheduled_arrival": "22:50"})
    c = build_context(s)
    assert "airport_curfew" in failed(_p(), s, c) and c.curfew == "23:00-07:00"


def test_turnaround_is_soft():
    results = check_all(S, C, _p(revised_arrival_delay_min=60))
    turn = next(r for r in results if r.constraint == "turnaround_next_leg")
    assert not turn.passed and not turn.hard and hard_ok(results)


def test_fallback_returns_safe_proposal():
    p = deterministic_resolution(S, C)
    assert p is not None and hard_ok(check_all(S, C, p))


def _ev(role: Role, **kw) -> Evaluation:
    return Evaluation(role=role, accept=False, counter_proposal=_p(**kw))


def test_select_counter_prefers_less_holding():
    # Same slot: the pilot's ground hold beats airborne holding, and an agent wins a tie with the solver
    evs = [_ev(Role.ATC, revised_arrival_delay_min=40, holding_min=15),
           _ev(Role.PILOT, revised_arrival_delay_min=25, holding_min=0)]
    p, role, reason = select_counter(S, C, evs)
    assert role == Role.PILOT and p.holding_min == 0 and "SOLVER" in reason


def test_select_counter_safety_beats_cost():
    # A cheaper counter on the closed runway must lose to a safe one
    evs = [_ev(Role.ATC, runway="R1", revised_arrival_delay_min=0), _ev(Role.GROUND)]
    assert select_counter(S, C, evs)[1] == Role.GROUND


def test_select_counter_none_without_counters():
    assert select_counter(S, C, [Evaluation(role=Role.ATC, accept=False)]) is None


def test_agents_only_see_their_domain():
    from atm.agents import ATCAgent, GroundAgent, PilotAgent

    agents = [ATCAgent(), PilotAgent(), GroundAgent()]
    seen = [set(a.context_fields) for a in agents]
    assert all(f in OpsContext.model_fields for s in seen for f in s)
    ground_prompt = GroundAgent().prompt(S, C, _p(slot_gap_min=1.5))
    assert "closed_runways" not in ground_prompt and "holding_fuel_available_min" not in ground_prompt
    assert '"wake_separation"' not in ground_prompt  # ATC check, not shown to ground


def test_prompt_carries_domain_checks():
    from atm.agents import ATCAgent

    c = build_context(S, _bank(("UA", 24, "HEAVY")))
    prompt = ATCAgent().prompt(S, c, _p(revised_arrival_delay_min=40, slot_gap_min=1.5))
    assert '"id": "wake_separation"' in prompt and '"passed": false' in prompt


def test_select_counter_merges_disjoint_fixes():
    # ATC fixes the slot, pilot moves the wait to the ground: each alone leaves the other failure
    current = _p(revised_arrival_delay_min=20, holding_min=10)
    evs = [_ev(Role.ATC, revised_arrival_delay_min=25, holding_min=10), _ev(Role.PILOT, revised_arrival_delay_min=20)]
    p, who, reason = select_counter(S, C, evs, current=current)
    assert who == "MERGED" and p.revised_arrival_delay_min == 25 and p.holding_min == 0 and hard_ok(check_all(S, C, p))


def test_merge_ignores_changes_outside_own_levers():
    from atm.negotiation import merge_counters

    current = _p(gate="G1", holding_min=10)
    evs = [_ev(Role.GROUND, gate="G2", holding_min=0), _ev(Role.PILOT, gate="G3", holding_min=5)]
    merged = merge_counters(current, evs)
    assert merged.gate == "G2" and merged.holding_min == 5


class _AcceptAll:
    def __init__(self, role): self.role = role
    def evaluate(self, s, c, p, history=""): return Evaluation(role=self.role, accept=True)


def test_consensus_with_holding_is_upgraded_to_ground_hold():
    # AA204: all agents accepted 8 min airborne holding at round 1; the ground-hold variant must be put to a vote
    from atm.negotiation import negotiate

    out = negotiate(S, C, _p(revised_arrival_delay_min=33, holding_min=8), [_AcceptAll(r) for r in Role])
    assert out.consensus and out.final.holding_min == 0 and out.final.revised_arrival_delay_min == 33
    assert len(out.turns) == 2 and out.turns[1].proposed_by == "GROUND_HOLD<consensus"
    assert "upgraded to ground hold" in out.turns[0].next_selection


def test_no_upgrade_without_holding_or_round_left(monkeypatch):
    from atm import negotiation

    out = negotiation.negotiate(S, C, _p(), [_AcceptAll(r) for r in Role])
    assert len(out.turns) == 1 and out.turns[0].next_selection is None
    monkeypatch.setattr(negotiation, "MAX_ROUNDS", 1)
    out = negotiation.negotiate(S, C, _p(revised_arrival_delay_min=33, holding_min=8), [_AcceptAll(r) for r in Role])
    assert out.final.holding_min == 8 and "no round left" in out.turns[0].next_selection
