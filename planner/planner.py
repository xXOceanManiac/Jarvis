
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class PlanStep:
    action: str
    args: dict[str, Any] = field(default_factory=dict)

@dataclass
class Plan:
    intent: str
    confidence: float
    reason: str
    steps: list[PlanStep]

class Planner:
    """
    V5.1 scaffold:
    keeps planning logic out of the realtime client so the system can grow from
    voice->tool into intent->plan->execute->verify.
    """
    def build(self, intent: str, context: dict[str, Any] | None = None) -> Plan:
        context = context or {}
        return Plan(intent=intent, confidence=0.4, reason="Planner scaffold", steps=[])
