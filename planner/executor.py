
from __future__ import annotations
from typing import Any

class Executor:
    def __init__(self, tools) -> None:
        self.tools = tools

    def run(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for step in steps:
            result = self.tools.execute(step)
            results.append({
                "ok": getattr(result, "ok", False),
                "message": getattr(result, "message", str(result)),
                "data": getattr(result, "data", None),
                "step": step,
            })
        return results
