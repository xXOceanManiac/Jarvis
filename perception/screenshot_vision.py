
from __future__ import annotations
from pathlib import Path

class ScreenshotVision:
    """
    Dedicated home for screenshot-based screen understanding.
    Current V4/V5 tool flow already does screenshots and vision summaries through tools.py;
    this module is where that logic should migrate as the architecture matures.
    """
    def summarize_path(self, image_path: str | Path) -> dict:
        return {"ok": True, "message": f"Screenshot available at {image_path}"}
