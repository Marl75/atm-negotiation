"""Offline tests (no API call): the supervisor's decision after `atm run`, and `atm check-proposal`."""

import io
import json
import sys

from atm import cli
from atm.negotiation import negotiate, record_decision
from atm.protocol import Evaluation, Role

from test_offline import C, S, _p


class _Agent:
    def __init__(self, role, accept=True):
        self.role, self.accept = role, accept

    def evaluate(self, s, c, p, history=""):
        return Evaluation(role=self.role, accept=self.accept, concerns=[f"{self.role.value} concern [x]"])


def _consensus():
    return negotiate(S, C, _p(), [_Agent(r) for r in Role])


def _answers(*a):
    it = iter(a)
    return lambda _prompt: next(it)


def _log_outcome(out) -> dict:
    return json.loads(open(out._log_path).read().splitlines()[-1])


def test_summary_lists_plan_checks_sources_and_concerns():
    out = _consensus()
    text = cli.summary(out)
    assert "Final plan" in text and f"gate {out.final.gate}" in text and f"runway {out.final.runway}" in text
    assert "hard" in text and "soft" in text and "wake_separation" in text and "REGULATORY" in text
    assert "PILOT concern" in text


def test_approval_is_recorded_in_the_log():
    out = _consensus()
    assert _log_outcome(out)["human_decision"] is None  # pending until the supervisor decides
    d = cli.decide(out, ask=_answers("maybe", "a", "slot confirmed with tower"))
    record_decision(out, d)
    logged = _log_outcome(out)["human_decision"]
    assert logged["decision"] == "approved" and logged["reason"] == "slot confirmed with tower"
    assert logged["decided_by"] == "approach supervisor" and logged["decided_at"].endswith("+00:00")
    assert not logged["auto"] and len(open(out._log_path).read().splitlines()) == len(out.turns) + 1


def test_rejection_and_auto_approve():
    out = _consensus()
    assert cli.decide(out, ask=_answers("r", "gate G2 under maintenance")).decision == "rejected"
    d = cli.decide(out, auto_approve=True, ask=lambda _: (_ for _ in ()).throw(AssertionError("asked")))
    assert d.decision == "approved" and d.auto


def test_no_safe_option_is_escalated_never_silent(monkeypatch):
    from atm import negotiation

    monkeypatch.setattr(negotiation, "deterministic_resolution", lambda s, c: None)
    out = negotiate(S, C, _p(), [_Agent(r, accept=False) for r in Role])
    assert out.final is None
    assert "ESCALATED: no safe option" in cli.summary(out)
    for d in (cli.decide(out, auto_approve=True), cli.decide(out, ask=_answers("divert to alternate"))):
        assert d.decision == "escalated" and d.reason.startswith("escalated: no safe option")
    record_decision(out, d)
    assert _log_outcome(out)["human_decision"]["decision"] == "escalated"


def test_check_proposal_from_log(monkeypatch, capsys):
    out = _consensus()
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"holding_min": 999, "revised_arrival_delay_min": 1000}'))
    cli.check_proposal(None, out._log_path, {"gate": "G2", "runway": None})
    res = json.loads(capsys.readouterr().out)
    failed = {r["constraint"] for r in res["checks"] if not r["passed"]}
    assert not res["hard_ok"] and "final_reserve_fuel" in failed
    assert res["proposal"]["gate"] == "G2" and all(r["source"] for r in res["checks"])
