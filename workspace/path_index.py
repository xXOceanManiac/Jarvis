
from __future__ import annotations
from pathlib import Path

class PathIndex:
    """
    V5.1 scaffold for future path indexing.
    """
    def __init__(self, roots: list[str]) -> None:
        self.roots = [Path(r).expanduser() for r in roots]

    def search(self, needle: str) -> list[str]:
        needle = str(needle or "").lower().strip()
        if not needle:
            return []
        matches: list[str] = []
        for root in self.roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if needle in path.name.lower():
                    matches.append(str(path))
                    if len(matches) >= 50:
                        return matches
        return matches
