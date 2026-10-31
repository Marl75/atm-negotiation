from ..protocol import Role
from .base import Agent


class ATCAgent(Agent):
    role = Role.ATC
    objectives = "- Respect runway wake separation\n- Avoid blocked taxiways\n- Maximise sector throughput"


class PilotAgent(Agent):
    role = Role.PILOT
    objectives = ("- Preserve fuel reserves\n- Ensure flight safety\n- Minimise turbulence\n"
                  "- Protect passengers' connections")


class GroundAgent(Agent):
    role = Role.GROUND
    objectives = "- Optimise gate utilisation\n- Avoid ground-crew overtime\n- Minimise turnaround delays"
