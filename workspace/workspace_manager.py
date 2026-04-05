
from __future__ import annotations
from pathlib import Path

class WorkspaceManager:
    """
    V5.1 scaffold for explicit workspace switching.
    Later this should own:
    - opening code in project path
    - opening terminal in project path
    - browser tabs for browser-only workspaces (like MSFL)
    - closing prior workspace windows when switching
    """
    def normalize_project_name(self, value: str) -> str:
        return " ".join(str(value or "").strip().lower().replace("_", " ").split())

    def project_hint_to_path(self, value: str) -> str:
        value = self.normalize_project_name(value)
        if "jarvis" in value:
            return str(Path("/home/tatel/Desktop/Jarvis.v5"))
        return ""
