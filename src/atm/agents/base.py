"""Each agent = its own system prompt + its own LLM call + its own domain constraints. Never merged into one prompt."""

from __future__ import annotations

import json
from typing import Callable

from ..context import PROVENANCE
from ..llm import ask_structured
from ..protocol import ConstraintResult, Disruption, Evaluation, OpsContext, Proposal, Role


class Agent:
    role: Role
    speaks_for: str  # who this agent represents in the real operation
    objectives: str  # filled by subclasses: hard limits, soft costs, levers
    context_fields: tuple[str, ...]  # the only OpsContext fields this agent may see
    checks: Callable[[Disruption, OpsContext, Proposal], list[ConstraintResult]]  # its domain checker

    @property
    def system(self) -> str:
        return (
            f"You are the {self.role.value} agent in a tactical air traffic disruption negotiation, speaking for "
            f"{self.speaks_for}. No ground delay programme is in force: this is the short-notice coordination "
            "that today happens by phone. The approach supervisor at the destination validates the final plan.\n"
            f"Your domain:\n{self.objectives}\n\n"
            "Rules:\n"
            "- You only see your own domain. Do not judge constraints of other roles.\n"
            "- The deterministic checks you receive are authoritative: do not recompute them. "
            "Never accept a proposal that fails a HARD check of your domain.\n"
            "- A failed SOFT check is a cost: you may accept it, and say so in `concerns`.\n"
            "- `dot_delay_causes_min` in the scenario are the DOT row's delay-cause minutes, attributed after the "
            "flight. Use them to understand the kind of disruption, not as a forecast: the slots and checks you "
            "receive do not use them, and they never justify accepting a failed HARD check.\n"
            "- `violated_constraints` lists only the constraint ids of failed checks you object to.\n"
            "- If you reject, give a counter-proposal that changes only what fixes your failed checks, "
            "uses only resources listed as available, and keeps every other field of the current proposal as is.\n"
            "- Keep `concerns` and `rationale` short and factual."
        )

    def domain_context(self, context: OpsContext) -> dict:
        """The agent's slice of the operational context, each value with its basis (DATA / ASSUMPTION)."""
        values = context.model_dump()
        return {f: {"value": values[f], "basis": PROVENANCE[f][0].value} for f in self.context_fields}

    def prompt(self, scenario: Disruption, context: OpsContext, proposal: Proposal, history: str = "") -> str:
        checks = [{"id": r.constraint, "hard": r.hard, "passed": r.passed, "detail": r.detail, "basis": r.basis.value}
                  for r in type(self).checks(scenario, context, proposal)]
        return (
            f"Scenario:\n{scenario.model_dump_json(indent=2)}\n\n"
            f"Your operational context:\n{json.dumps(self.domain_context(context), indent=2)}\n\n"
            f"Proposal:\n{proposal.model_dump_json(indent=2)}\n\n"
            f"Deterministic checks of your domain on this proposal:\n{json.dumps(checks, indent=2)}\n\n"
            f"Negotiation so far:\n{history or '(first round)'}"
        )

    def evaluate(self, scenario: Disruption, context: OpsContext, proposal: Proposal, history: str = "") -> Evaluation:
        ev = ask_structured(self.system, self.prompt(scenario, context, proposal, history), Evaluation)
        ev.role = self.role  # the agent cannot speak for another role
        return ev
