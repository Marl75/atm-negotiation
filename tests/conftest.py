"""Offline tests write their logs, eval and audit results to a temporary folder, never to logs/ or eval/."""

import pytest


@pytest.fixture(autouse=True)
def _tmp_outputs(tmp_path, monkeypatch):
    from atm import audit, evaluate, negotiation

    monkeypatch.setattr(negotiation, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(evaluate, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path / "eval" / "audit")
