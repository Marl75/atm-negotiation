"""Each agent = its own system prompt + its own LLM call + its own domain constraints. Never merged into one prompt."""

from __future__ import annotations

from ..llm import ask_structured
from ..protocol import Disruption, Evaluation, OpsContext, Proposal, Role


class Agent:
    role: Role
    objectives: str  # filled by subclasses

    @property
    def system(self) -> str:
        return (
            f"You are the {self.role.value} agent in an air traffic disruption negotiation.\n"
            f"Your objectives (your domain only):\n{self.objectives}\n"
            "You only see your own domain. Evaluate the proposal, list violated constraints, "
            "and if you reject it, give a counter-proposal. Never accept a proposal that breaks a safety margin."
        )

    def evaluate(self, scenario: Disruption, context: OpsContext, proposal: Proposal, history: str = "") -> Evaluation:
        # TODO: give each agent only the context fields of its own domain
        user = (
            f"Scenario:\n{scenario.model_dump_json(indent=2)}\n\n"
            f"Operational context:\n{context.model_dump_json(indent=2)}\n\n"
            f"Proposal:\n{proposal.model_dump_json(indent=2)}\n\n"
            f"Negotiation so far:\n{history or '(first round)'}"
        )
        ev = ask_structured(self.system, user, Evaluation)
        ev.role = self.role  # the agent cannot speak for another role
        return ev
