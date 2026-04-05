from __future__ import annotations
import base64
import json
import os
import re
import shlex
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import requests
from config import CONFIG
from memory import MemoryStore
from episodic_memory import EpisodicMemory
from semantic_memory import SemanticMemory
from procedural_memory import ProceduralMemory
from working_memory import WorkingMemory
from dream_manager import DreamManager
from behavior_learning import BehaviorLearningEngine
from utils import command_exists, ensure_dir, kill_existing, log_event, run_cmd


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


HARDCODED_HA_SCRIPTS: dict[str, str] = {
    # Lights
    "lights on": "jarvis_lights_on",
    "turn on lights": "jarvis_lights_on",
    "turn on my lights": "jarvis_lights_on",
    "lights off": "jarvis_lights_off",
    "turn off lights": "jarvis_lights_off",
    "turn off my lights": "jarvis_lights_off",
    "dim lights": "jarvis_lights_dim",
    "lights dim": "jarvis_lights_dim",
    "brighten lights": "jarvis_lights_brighten",
    "lights brighten": "jarvis_lights_brighten",
    "default lights": "jarvis_lights_default",
    "natural lights": "jarvis_lights_natural_75",
    "red lights": "jarvis_lights_red",
    "blue lights": "jarvis_lights_blue",
    "green lights": "jarvis_lights_green",
    "purple lights": "jarvis_lights_purple",
    "movie mode": "jarvis_movie_mode",
    "work mode": "jarvis_work_mode",
    "night mode": "jarvis_night_mode",
    "party mode": "jarvis_party_mode",
    # Xbox
    "xbox on": "jarvis_xbox_on",
    "turn on xbox": "jarvis_xbox_on",
    "xbox off": "jarvis_xbox_off",
    "turn off xbox": "jarvis_xbox_off",
    "pause xbox": "jarvis_xbox_pause",
    "resume xbox": "jarvis_xbox_resume",
    "play xbox": "jarvis_xbox_resume",
    "xbox youtube": "jarvis_xbox_youtube",
    "youtube on xbox": "jarvis_xbox_youtube",
    "xbox netflix": "jarvis_xbox_netflix",
    "netflix on xbox": "jarvis_xbox_netflix",
    "xbox spotify": "jarvis_xbox_spotify",
    "spotify on xbox": "jarvis_xbox_spotify",
    "watch youtube": "jarvis_watch_youtube",
    "watch netflix": "jarvis_watch_netflix",
    "play spotify": "jarvis_play_spotify",
    "xbox volume up": "jarvis_xbox_volume_up",
    "volume up on xbox": "jarvis_xbox_volume_up",
    "xbox volume down": "jarvis_xbox_volume_down",
    "volume down on xbox": "jarvis_xbox_volume_down",
    "good night": "jarvis_good_night",
}
EXACT_HA_SCRIPT_NAMES = set(HARDCODED_HA_SCRIPTS.values())


def run_ha_script(script_name: str) -> ToolResult:
    token = os.getenv("HOME_ASSISTANT_API_KEY", "").strip()
    if not token:
        return ToolResult(False, "HOME_ASSISTANT_API_KEY is not set.")
    base_url = (
        os.getenv("HOME_ASSISTANT_URL", "http://localhost:8123").strip().rstrip("/")
    )
    url = f"{base_url}/api/services/script/turn_on"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = {"entity_id": f"script.{script_name}"}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=5)
        if response.status_code >= 400:
            return ToolResult(
                False,
                f"Home Assistant error {response.status_code}: {response.text[:300]}",
            )
        return ToolResult(True, f"Executed Home Assistant script: {script_name}")
    except Exception as e:
        return ToolResult(False, f"Failed to run Home Assistant script: {e}")


ACTION_ENUM = [
    "open_app",
    "close_app",
    "open_url_key",
    "open_url_keys",
    "open_url_raw",
    "web_search",
    "open_code_folder",
    "open_terminal_here",
    "smart_action",
    "summarize_screen",
    "save_context",
    "resume_last_context",
    "run_routine",
    "save_routine",
    "backfill_memory",
    "run_dream_pass",
    "run_ha_script",
    "list_windows",
    "get_active_window",
    "desktop_state",
    "screen_context",
    "list_files",
    "read_file",
    "write_file",
    "mode_lock_in",
    "volume_change",
    "volume_set",
    "mute_toggle",
    "screenshot",
    "tell_time",
    "projector_on",
    "projector_off",
    "sleep",
    "restart",
    "shutdown",
    "confirm_pending",
    "cancel_pending",
]


def _step_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTION_ENUM},
            "app": {"type": "string"},
            "apps": {"type": "array", "items": {"type": "string"}},
            "url_key": {"type": "string"},
            "url_keys": {"type": "array", "items": {"type": "string"}},
            "url": {"type": "string"},
            "urls": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "delta": {"type": "integer"},
            "value": {"type": "integer"},
            "project_path": {"type": "string"},
            "context_name": {"type": "string"},
            "routine_name": {"type": "string"},
            "script_name": {"type": "string"},
            "notes": {"type": "string"},
            "layout": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "description": {"type": "string"},
            "include_screenshot": {"type": "boolean"},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ACTION_ENUM},
                        "app": {"type": "string"},
                        "apps": {"type": "array", "items": {"type": "string"}},
                        "url_key": {"type": "string"},
                        "url_keys": {"type": "array", "items": {"type": "string"}},
                        "url": {"type": "string"},
                        "urls": {"type": "array", "items": {"type": "string"}},
                        "query": {"type": "string"},
                        "delta": {"type": "integer"},
                        "value": {"type": "integer"},
                        "project_path": {"type": "string"},
                        "context_name": {"type": "string"},
                        "routine_name": {"type": "string"},
                        "script_name": {"type": "string"},
                        "notes": {"type": "string"},
                        "layout": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                        "include_screenshot": {"type": "boolean"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }


class ToolRegistry:
    def __init__(self) -> None:
        self.pending_action: dict[str, Any] | None = None
        self.pending_expires_at: float = 0.0
        self.confirmation_timeout_seconds = 12.0
        self.memory = MemoryStore()
        self.episodes = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.procedural = ProceduralMemory()
        self.working = WorkingMemory()
        self.dream = DreamManager()
        self.behavior = BehaviorLearningEngine(
            memory=self.memory,
            semantic=self.semantic,
            procedural=self.procedural,
            working=self.working,
            episodes=self.episodes,
        )

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "desktop_action",
                "description": (
                    "Execute local desktop actions. Supports single actions, action arrays, "
                    "persistent work contexts, named routines, Home Assistant scripts, "
                    "desktop awareness, file access, and memory operations."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ACTION_ENUM},
                        "actions": {
                            "type": "array",
                            "items": _step_schema(),
                            "minItems": 1,
                        },
                        "app": {"type": "string"},
                        "apps": {"type": "array", "items": {"type": "string"}},
                        "url_key": {"type": "string"},
                        "url_keys": {"type": "array", "items": {"type": "string"}},
                        "url": {"type": "string"},
                        "urls": {"type": "array", "items": {"type": "string"}},
                        "query": {"type": "string"},
                        "delta": {"type": "integer"},
                        "value": {"type": "integer"},
                        "project_path": {"type": "string"},
                        "context_name": {"type": "string"},
                        "routine_name": {"type": "string"},
                        "script_name": {"type": "string"},
                        "notes": {"type": "string"},
                        "layout": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                        "include_screenshot": {"type": "boolean"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "steps": {
                            "type": "array",
                            "items": _step_schema(),
                            "minItems": 1,
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ]

    def _episode(
        self,
        kind: str,
        summary: str,
        *,
        tags: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.episodes.append(kind, summary, tags=tags or [], data=data or {})
        except Exception:
            pass

    def _remember_last_request(self, payload: dict[str, Any]) -> None:
        try:
            request_text = str(payload.get("request_text", "")).strip()
            if request_text:
                self.working.set_user_request(request_text)
        except Exception:
            pass

    def _remember_tool_result(
        self,
        payload: dict[str, Any],
        result: ToolResult,
    ) -> ToolResult:
        action = str(payload.get("action", "")).strip() or "multi_action"
        try:
            self.working.set_tool_result(
                action=action,
                ok=result.ok,
                message=result.message,
                data=result.data or {},
            )
        except Exception:
            pass
        return result

    def _set_pending(self, payload: dict[str, Any]) -> ToolResult:
        self.pending_action = payload
        self.pending_expires_at = time.time() + self.confirmation_timeout_seconds
        try:
            self.working.write(
                {
                    "pending_confirmation": str(payload.get("action", "")).strip(),
                }
            )
        except Exception:
            pass
        return ToolResult(True, f"Awaiting confirmation for {payload['action']}.")

    def _clear_pending(self) -> None:
        self.pending_action = None
        self.pending_expires_at = 0.0
        try:
            self.working.write({"pending_confirmation": ""})
        except Exception:
            pass

    def _resolve_pending(self, confirm: bool) -> ToolResult:
        if not self.pending_action:
            return ToolResult(False, "There is no pending action to confirm.")
        if time.time() > self.pending_expires_at:
            self._clear_pending()
            return ToolResult(False, "The pending confirmation expired.")
        if not confirm:
            self._clear_pending()
            return ToolResult(True, "Cancelled.")
        payload = self.pending_action
        self._clear_pending()
        return self.execute(payload)

    def _launch(self, cmd: str, cwd: str | None = None) -> None:
        subprocess.Popen(
            shlex.split(cmd),
            cwd=cwd or None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _open_app_key(self, app_key: str, cwd: str | None = None) -> ToolResult:
        cmd = CONFIG.get("apps", {}).get(app_key)
        if not cmd:
            return ToolResult(False, f"Unknown app: {app_key}")
        self._launch(cmd, cwd=cwd)
        return ToolResult(True, f"Opened {app_key}.")

    def _resolve_project_path(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        projects = CONFIG.get("projects", {})
        if raw in projects and isinstance(projects[raw], dict):
            return str(projects[raw].get("path", "")).strip()
        return str(Path(raw).expanduser())

    def _run_layout_hook(self, context: dict[str, Any]) -> None:
        script = Path(str(CONFIG.get("layout_script", "")).strip()).expanduser()
        if not script.exists() or not os.access(script, os.X_OK):
            return
        env = os.environ.copy()
        env["JARVIS_CONTEXT_JSON"] = json.dumps(context)
        subprocess.Popen(
            [str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def _capture_screenshot(self) -> tuple[bool, str]:
        shot_dir = ensure_dir(CONFIG.get("screenshot_dir", "~/Pictures/Screenshots"))
        filename = shot_dir / f"screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png"
        if command_exists("gnome-screenshot"):
            run_cmd(["gnome-screenshot", "-f", str(filename)])
        elif command_exists("spectacle"):
            run_cmd(["spectacle", "-b", "-n", "-o", str(filename)])
        elif command_exists("grim"):
            run_cmd(["grim", str(filename)])
        else:
            return False, "No supported screenshot tool found."
        return True, str(filename)

    def _get_active_window(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "window_id": "",
            "pid": "",
            "title": "",
            "class": "",
            "workspace": None,
        }
        if command_exists("xdotool"):
            r = run_cmd(["xdotool", "getactivewindow"], capture=True)
            if r.returncode == 0:
                wid = r.stdout.strip()
                data["window_id"] = wid
                r_name = run_cmd(["xdotool", "getwindowname", wid], capture=True)
                if r_name.returncode == 0:
                    data["title"] = r_name.stdout.strip()
                r_pid = run_cmd(["xdotool", "getwindowpid", wid], capture=True)
                if r_pid.returncode == 0:
                    data["pid"] = r_pid.stdout.strip()
        if command_exists("wmctrl"):
            r = run_cmd(["wmctrl", "-lx"], capture=True)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    parts = line.split(None, 4)
                    if len(parts) < 5:
                        continue
                    wid, workspace, wm_class, host, title = parts
                    if wid.lower() == str(data["window_id"]).lower():
                        data["workspace"] = workspace
                        data["class"] = wm_class
                        if not data["title"]:
                            data["title"] = title
                        break
        return data

    def _list_windows(self) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        if not command_exists("wmctrl"):
            return windows
        r = run_cmd(["wmctrl", "-lx"], capture=True)
        if r.returncode != 0:
            return windows
        active_id = ""
        if command_exists("xdotool"):
            r_active = run_cmd(["xdotool", "getactivewindow"], capture=True)
            if r_active.returncode == 0:
                active_id = r_active.stdout.strip().lower()
        for line in r.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            wid, workspace, wm_class, host, title = parts
            pid = ""
            if command_exists("xdotool"):
                r_pid = run_cmd(["xdotool", "getwindowpid", wid], capture=True)
                if r_pid.returncode == 0:
                    pid = r_pid.stdout.strip()
            windows.append(
                {
                    "window_id": wid,
                    "pid": pid,
                    "workspace": workspace,
                    "class": wm_class,
                    "title": title,
                    "is_active": wid.lower() == active_id,
                }
            )
        return windows

    def _normalize_ha_script_name(self, raw_name: str) -> str:
        norm = raw_name.lower().replace("-", " ").replace("_", " ")
        norm = " ".join(norm.split())
        aliases = {
            "movie mode": "movie_mode_full",
            "start movie mode": "movie_mode_full",
            "turn on a movie": "movie_mode_full",
            "turn on the movie": "movie_mode_full",
            "put on a movie": "movie_mode_full",
            "watch a movie": "movie_mode_full",
            "movie mode full": "movie_mode_full",
            "start movie mode on xbox": "movie_mode_full",
            "movie mode on xbox": "movie_mode_full",
            "netflix": "netflix_on_xbox",
            "netflix on xbox": "netflix_on_xbox",
            "open netflix on xbox": "netflix_on_xbox",
            "start netflix on xbox": "netflix_on_xbox",
        }
        chosen = aliases.get(norm)
        if chosen:
            return chosen
        routines_cfg = CONFIG.get("routines", {})
        for key in routines_cfg.keys():
            key_norm = key.lower().replace("-", " ").replace("_", " ")
            key_norm = " ".join(key_norm.split())
            if key_norm == norm or norm in key_norm or key_norm in norm:
                return key
        return raw_name.strip().lower().replace(" ", "_")

    def _match_ha_script_from_text(self, text: str) -> str:
        q = " ".join(
            str(text or "").strip().lower().replace("_", " ").replace("-", " ").split()
        )
        if not q:
            return ""

        phrase_order = [
            (
                [
                    "turn the lights on",
                    "turn my lights on",
                    "turn on the lights",
                    "turn on my lights",
                    "lights on",
                ],
                "jarvis_lights_on",
            ),
            (
                [
                    "turn the lights off",
                    "turn my lights off",
                    "turn off the lights",
                    "turn off my lights",
                    "lights off",
                ],
                "jarvis_lights_off",
            ),
            (
                ["dim the lights", "dim my lights", "dim lights", "lights dim"],
                "jarvis_lights_dim",
            ),
            (
                [
                    "brighten the lights",
                    "brighten my lights",
                    "brighten lights",
                    "lights brighten",
                ],
                "jarvis_lights_brighten",
            ),
            (
                ["default lights", "lights default", "reset lights"],
                "jarvis_lights_default",
            ),
            (
                ["natural lights", "lights natural", "natural 75"],
                "jarvis_lights_natural_75",
            ),
            (
                ["red lights", "lights red", "turn lights red", "make the lights red"],
                "jarvis_lights_red",
            ),
            (
                [
                    "blue lights",
                    "lights blue",
                    "turn lights blue",
                    "make the lights blue",
                ],
                "jarvis_lights_blue",
            ),
            (
                [
                    "green lights",
                    "lights green",
                    "turn lights green",
                    "make the lights green",
                ],
                "jarvis_lights_green",
            ),
            (
                [
                    "purple lights",
                    "lights purple",
                    "turn lights purple",
                    "make the lights purple",
                ],
                "jarvis_lights_purple",
            ),
            (
                ["movie mode", "set movie mode", "movie lights", "watch a movie"],
                "jarvis_movie_mode",
            ),
            (
                [
                    "work mode",
                    "set work mode",
                    "work lights",
                    "lets get to work lights",
                ],
                "jarvis_work_mode",
            ),
            (
                ["night mode", "set night mode", "good night lights"],
                "jarvis_night_mode",
            ),
            (["party mode", "turn on party mode"], "jarvis_party_mode"),
            (["xbox on", "turn on xbox", "power on xbox"], "jarvis_xbox_on"),
            (["xbox off", "turn off xbox", "power off xbox"], "jarvis_xbox_off"),
            (
                [
                    "open youtube on xbox",
                    "youtube on xbox",
                    "resume youtube on the xbox",
                    "resume youtube on xbox",
                ],
                "jarvis_xbox_youtube",
            ),
            (
                ["open netflix on xbox", "netflix on xbox", "resume netflix on xbox"],
                "jarvis_xbox_netflix",
            ),
            (
                ["open spotify on xbox", "spotify on xbox", "play spotify on xbox"],
                "jarvis_xbox_spotify",
            ),
            (["watch youtube", "watch youtube on xbox"], "jarvis_watch_youtube"),
            (["watch netflix", "watch netflix on xbox"], "jarvis_watch_netflix"),
            (["play spotify", "play spotify on xbox"], "jarvis_play_spotify"),
            (["pause the xbox", "pause xbox", "xbox pause"], "jarvis_xbox_pause"),
            (
                ["resume the xbox", "resume xbox", "xbox resume", "play the xbox"],
                "jarvis_xbox_resume",
            ),
            (
                ["xbox volume up", "volume up on xbox", "turn xbox volume up"],
                "jarvis_xbox_volume_up",
            ),
            (
                ["xbox volume down", "volume down on xbox", "turn xbox volume down"],
                "jarvis_xbox_volume_down",
            ),
            (["good night"], "jarvis_good_night"),
        ]

        for phrases, script_name in phrase_order:
            if any(p in q for p in phrases):
                return script_name

        # fallback token logic for shorter utterances
        if "light" in q or "lights" in q:
            if "off" in q:
                return "jarvis_lights_off"
            if "on" in q:
                return "jarvis_lights_on"
            if "dim" in q:
                return "jarvis_lights_dim"
            if "bright" in q:
                return "jarvis_lights_brighten"
            if "red" in q:
                return "jarvis_lights_red"
            if "blue" in q:
                return "jarvis_lights_blue"
            if "green" in q:
                return "jarvis_lights_green"
            if "purple" in q:
                return "jarvis_lights_purple"
            if "movie" in q:
                return "jarvis_movie_mode"
            if "work" in q:
                return "jarvis_work_mode"
            if "night" in q:
                return "jarvis_night_mode"
            if "party" in q:
                return "jarvis_party_mode"

        if "xbox" in q:
            if "pause" in q:
                return "jarvis_xbox_pause"
            if "resume" in q or "play" in q:
                return "jarvis_xbox_resume"
            if "off" in q:
                return "jarvis_xbox_off"
            if "on" in q:
                return "jarvis_xbox_on"
            if "youtube" in q:
                return "jarvis_xbox_youtube"
            if "netflix" in q:
                return "jarvis_xbox_netflix"
            if "spotify" in q:
                return "jarvis_xbox_spotify"
            if "volume up" in q:
                return "jarvis_xbox_volume_up"
            if "volume down" in q:
                return "jarvis_xbox_volume_down"
        return ""

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str) and payload.get("output_text"):
            return str(payload["output_text"]).strip()
        parts: list[str] = []
        for item in payload.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                txt = content.get("text") or content.get("output_text")
                if txt:
                    parts.append(str(txt))
        return "\n".join(parts).strip()

    def _openai_responses(
        self, body: dict[str, Any]
    ) -> tuple[bool, dict[str, Any] | str]:
        api_key = str(
            CONFIG.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
        ).strip()
        if not api_key:
            return False, "OPENAI_API_KEY is not set."
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=45,
            )
            if response.status_code >= 400:
                return (
                    False,
                    f"OpenAI Responses error {response.status_code}: {response.text[:400]}",
                )
            return True, response.json()
        except Exception as e:
            return False, str(e)

    def _image_to_data_url(self, path: str) -> str:
        raw = Path(path).read_bytes()
        mime = "image/png"
        suffix = Path(path).suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"
        return f"data:{mime};base64," + base64.b64encode(raw).decode("utf-8")

    def _summarize_screenshot_with_vision(
        self, image_path: str, prompt: str
    ) -> ToolResult:
        body = {
            "model": CONFIG.get("vision_model", "gpt-4.1-mini"),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": self._image_to_data_url(image_path),
                            "detail": "high",
                        },
                    ],
                }
            ],
        }
        ok, payload = self._openai_responses(body)
        if not ok:
            return ToolResult(False, str(payload))
        summary = self._extract_response_text(
            payload if isinstance(payload, dict) else {}
        )
        if not summary:
            return ToolResult(False, "Vision analysis returned no summary.")
        return ToolResult(
            True, "Summarized current screen.", {"summary": summary, "path": image_path}
        )

    def _web_search_summary(self, query: str) -> ToolResult:
        body = {
            "model": CONFIG.get("responses_model", "gpt-5.4-mini"),
            "tools": [{"type": "web_search"}],
            "input": f"Search the web for: {query}. Give a concise factual summary. If the query is local or time-sensitive, say so clearly and summarize the best available results.",
            "include": ["web_search_call.action.sources"],
        }
        ok, payload = self._openai_responses(body)
        if not ok:
            return ToolResult(False, str(payload))
        data = payload if isinstance(payload, dict) else {}
        summary = self._extract_response_text(data)
        sources = []
        for item in data.get("output", []) or []:
            if item.get("type") == "web_search_call":
                action = item.get("action") or {}
                for src in action.get("sources", []) or []:
                    url = src.get("url") or src.get("site") or src.get("title")
                    if url:
                        sources.append(url)
        webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return ToolResult(
            True,
            f"Searched the web for {query}.",
            {"summary": summary, "sources": sources[:8], "query": query},
        )

    def _resolve_code_file_from_window(
        self, active: dict[str, Any], project_path: str
    ) -> str:
        title = str(active.get("title", "")).strip()
        if not title or not project_path or not Path(project_path).exists():
            return ""
        head = re.split(r"\s[-—]\s", title)[0].strip()
        if not head:
            return ""
        root = Path(project_path)
        exact = list(root.rglob(head))
        if exact:
            return str(exact[0])
        exact2 = list(root.rglob(head + ".*"))
        if exact2:
            return str(exact2[0])
        return ""

    def _execute_many(self, actions: list[dict[str, Any]]) -> ToolResult:
        results: list[ToolResult] = []
        for item in actions:
            single = dict(item)
            single.pop("actions", None)
            results.append(self._execute_one(single))
        ok = all(r.ok for r in results)
        message = " | ".join(r.message for r in results)
        if ok:
            project_path = next(
                (
                    str(a.get("project_path", "")).strip()
                    for a in actions
                    if str(a.get("project_path", "")).strip()
                ),
                "",
            )
            apps = [
                str(a.get("app", "")).strip().lower()
                for a in actions
                if str(a.get("app", "")).strip()
            ]
            url_keys: list[str] = []
            urls: list[str] = []
            for a in actions:
                if str(a.get("url_key", "")).strip():
                    url_keys.append(str(a["url_key"]).strip().lower())
                for key in a.get("url_keys", []):
                    if str(key).strip():
                        url_keys.append(str(key).strip().lower())
                if str(a.get("url", "")).strip():
                    urls.append(str(a["url"]).strip())
            url_keys = self.memory._unique_list(url_keys)
            urls = self.memory._unique_list(urls)
            meaningful_apps = [
                a for a in apps if a not in {"chrome", "google chrome", "browser"}
            ]
            meaningful_urls = [k for k in url_keys if k not in {"chatgpt", "google"}]
            if project_path or meaningful_apps or meaningful_urls or len(urls) >= 2:
                name = (
                    Path(project_path).name
                    if project_path
                    else f"Session {time.strftime('%Y-%m-%d %H:%M')}"
                )
                ctx = self.memory.remember_context(
                    name=name,
                    project_path=project_path,
                    apps=apps,
                    url_keys=url_keys,
                    urls=urls,
                    notes="Auto-saved successful workspace",
                    source="auto",
                )
                self.working.write(
                    {
                        "active_workspace": ctx["name"],
                        "active_context_name": ctx["name"],
                    }
                )
        return ToolResult(ok, message, {"results": [r.__dict__ for r in results]})

    def execute(self, payload: dict[str, Any]) -> ToolResult:
        log_event("tool_execute", {"payload": payload})
        self._remember_last_request(payload)
        action_name = str(payload.get("action", "")).strip()
        self._episode(
            "tool_request",
            f"Requested tool action: {action_name or 'multi_action'}",
            tags=["tool"],
            data=payload,
        )
        actions = payload.get("actions")
        if isinstance(actions, list) and actions:
            result = self._execute_many(actions)
            return self._remember_tool_result(payload, result)
        action = str(payload.get("action", "")).strip()
        if not action:
            return self._remember_tool_result(
                payload,
                ToolResult(False, "No action was provided."),
            )
        result = self._execute_one(payload)
        return self._remember_tool_result(payload, result)

    def _execute_one(self, payload: dict[str, Any]) -> ToolResult:
        action = str(payload.get("action", "")).strip()
        if action == "confirm_pending":
            return self._resolve_pending(True)
        if action == "cancel_pending":
            return self._resolve_pending(False)
        if action in {"sleep", "restart", "shutdown"}:
            return self._set_pending(payload)
        if action == "run_ha_script":
            raw_name = str(payload.get("script_name", "")).strip()
            if not raw_name:
                return ToolResult(False, "A script name is required.")
            chosen = self._normalize_ha_script_name(raw_name)
            result = run_ha_script(chosen)
            if result.ok:
                self._episode(
                    "tool_action",
                    f"Ran Home Assistant script: {chosen}",
                    tags=["home_assistant", "script"],
                    data={"action": action, "script_name": chosen},
                )
                self.working.write(
                    {
                        "last_tool_action": "run_ha_script",
                        "active_media_flow": (
                            chosen if "movie" in chosen or "netflix" in chosen else ""
                        ),
                        "current_mode": "movie" if "movie" in chosen else "",
                    }
                )
            return result
        if action == "smart_action":
            request_text = str(
                payload.get("request_text", "") or payload.get("query", "")
            ).strip()
            lowered = " ".join(request_text.lower().split())
            script = self._match_ha_script_from_text(lowered)
            if script:
                return self._execute_one(
                    {
                        "action": "run_ha_script",
                        "script_name": script,
                        "request_text": request_text,
                    }
                )
            if any(
                x in lowered
                for x in [
                    "what am i looking at",
                    "what's on my screen",
                    "summarize the tab",
                    "summarize the screen",
                    "what is on my screen",
                    "current tab",
                    "screen right now",
                ]
            ):
                return self._execute_one(
                    {"action": "summarize_screen", "request_text": request_text}
                )
            if any(
                x in lowered
                for x in [
                    "movies playing near me",
                    "search for",
                    "look up",
                    "search the web",
                    "latest ",
                    "today",
                    "near me",
                ]
            ):
                return self._execute_one(
                    {
                        "action": "web_search",
                        "query": request_text,
                        "request_text": request_text,
                    }
                )
            if any(
                x in lowered
                for x in [
                    "let's get to work",
                    "lets get to work",
                    "get to work",
                    "open my workspace",
                    "switch to",
                    "work on ",
                ]
            ):
                return self._execute_one(
                    {
                        "action": "resume_last_context",
                        "query": request_text,
                        "request_text": request_text,
                    }
                )
            return ToolResult(False, "No deterministic smart action matched.")
        if action == "summarize_screen":
            ok, shot = self._capture_screenshot()
            if not ok:
                return ToolResult(False, shot)
            desktop = {
                "active_window": self._get_active_window(),
                "windows": self._list_windows(),
            }
            active = desktop.get("active_window", {}) or {}
            request_text = str(
                payload.get("request_text", "")
                or "Summarize what is visible on this screen."
            ).strip()
            project_path = self._resolve_project_path(
                self.behavior.resolve_active_project(
                    desktop, request_text=request_text
                ).get("project_path", "")
            )
            code_file = self._resolve_code_file_from_window(active, project_path)
            code_snippet = ""
            if code_file and Path(code_file).exists():
                try:
                    code_snippet = Path(code_file).read_text(
                        encoding="utf-8", errors="ignore"
                    )[:5000]
                except Exception:
                    code_snippet = ""
            prompt = (
                f"Analyze this screenshot and describe exactly what is visible. "
                f"Identify the application, summarize the visible content, and explain what the user is likely looking at. "
                f"Do not guess if the screenshot is unclear; say what you can actually see. "
                f"Active window metadata: {json.dumps(active)}. "
            )
            if code_snippet:
                prompt += f"Likely active file path: {code_file}. File snippet for grounding: {code_snippet}"
            result = self._summarize_screenshot_with_vision(shot, prompt)
            if result.ok:
                data = result.data or {}
                data.update({"desktop_state": desktop, "code_file": code_file})
                result.data = data
            return result
        if action == "backfill_memory":
            count = self.memory.backfill_from_logs()
            self._episode(
                "tool_action",
                f"Backfilled memory from logs: {count}",
                tags=["memory"],
                data={"action": action, "count": count},
            )
            return ToolResult(
                True,
                f"Imported {count} historical contexts from logs.",
                {"count": count},
            )
        if action == "run_dream_pass":
            result = self.dream.run_once()
            self._episode(
                "tool_action",
                "Ran dream pass.",
                tags=["memory", "dream"],
                data={"action": action, **result},
            )
            return ToolResult(True, "Dream pass completed.", result)
        if action == "list_windows":
            windows = self._list_windows()
            self._episode(
                "tool_action",
                f"Listed {len(windows)} desktop windows.",
                tags=["desktop", "awareness"],
                data={"action": action, "count": len(windows)},
            )
            return ToolResult(
                True, f"Found {len(windows)} open windows.", {"windows": windows}
            )
        if action == "get_active_window":
            active = self._get_active_window()
            self.working.write(
                {"screen_focus": active, "last_tool_action": "get_active_window"}
            )
            self._episode(
                "tool_action",
                f"Checked active window: {active.get('title') or 'Unknown'}",
                tags=["desktop", "awareness"],
                data={"action": action, "active_window": active},
            )
            return ToolResult(
                True,
                f"Active window: {active.get('title') or 'Unknown'}",
                {"active_window": active},
            )
        if action == "desktop_state":
            windows = self._list_windows()
            active = self._get_active_window()
            data = {
                "active_window": active,
                "windows": windows,
            }
            if bool(payload.get("include_screenshot", False)):
                ok, shot = self._capture_screenshot()
                if ok:
                    data["screenshot_path"] = shot
                else:
                    data["screenshot_error"] = shot
            self.working.write(
                {"screen_focus": active, "last_tool_action": "desktop_state"}
            )
            self._episode(
                "tool_action",
                "Collected desktop state.",
                tags=["desktop", "awareness"],
                data={
                    "action": action,
                    "active_window": active,
                    "window_count": len(windows),
                },
            )
            return ToolResult(True, "Collected desktop state.", data)
        if action == "screen_context":
            # Safe fallback to desktop state if no dedicated screen_context store is wired yet
            windows = self._list_windows()
            active = self._get_active_window()
            data = {
                "active_window": active,
                "windows": windows,
            }
            return ToolResult(True, "Loaded current screen context.", data)
        if action == "open_app":
            app_key = str(payload.get("app", "")).strip().lower()
            result = self._open_app_key(app_key)
            if result.ok:
                self._episode(
                    "tool_action",
                    f"Opened app: {app_key}",
                    tags=["desktop", "app"],
                    data={"action": action, "app": app_key},
                )
                self.working.write({"last_tool_action": "open_app"})
            return result
        if action == "close_app":
            app_key = str(payload.get("app", "")).strip().lower()
            cmd = CONFIG.get("apps", {}).get(app_key)
            if not cmd:
                return ToolResult(False, f"Unknown app: {app_key}")
            process_name = shlex.split(cmd)[0]
            kill_existing(process_name)
            self._episode(
                "tool_action",
                f"Closed app: {app_key}",
                tags=["desktop", "app"],
                data={"action": action, "app": app_key},
            )
            self.working.write({"last_tool_action": "close_app"})
            return ToolResult(True, f"Closed {app_key}.")
        if action == "open_url_key":
            url_key = str(payload.get("url_key", "")).strip().lower()
            url = CONFIG.get("urls", {}).get(url_key)
            if not url:
                return ToolResult(False, f"Unknown URL key: {url_key}")
            webbrowser.open(url)
            self._episode(
                "tool_action",
                f"Opened URL key: {url_key}",
                tags=["browser", "url"],
                data={"action": action, "url_key": url_key},
            )
            self.working.write({"last_tool_action": "open_url_key"})
            return ToolResult(True, f"Opened {url_key}.")
        if action == "open_url_keys":
            keys = [
                str(x).strip().lower()
                for x in payload.get("url_keys", [])
                if str(x).strip()
            ]
            if not keys:
                return ToolResult(False, "No URL keys were provided.")
            results: list[str] = []
            all_ok = True
            for key in keys:
                url = CONFIG.get("urls", {}).get(key)
                if not url:
                    all_ok = False
                    results.append(f"Unknown URL key: {key}")
                    continue
                webbrowser.open(url)
                results.append(f"Opened {key}.")
            if all_ok:
                self._episode(
                    "tool_action",
                    f"Opened URL keys: {', '.join(keys)}",
                    tags=["browser", "url"],
                    data={"action": action, "url_keys": keys},
                )
                self.working.write({"last_tool_action": "open_url_keys"})
            return ToolResult(all_ok, " | ".join(results), {"url_keys": keys})
        if action == "open_url_raw":
            url = str(payload.get("url", "")).strip()
            if not url:
                return ToolResult(False, "No URL provided.")
            webbrowser.open(url)
            self._episode(
                "tool_action",
                f"Opened raw URL: {url}",
                tags=["browser", "url"],
                data={"action": action, "url": url},
            )
            self.working.write({"last_tool_action": "open_url_raw"})
            return ToolResult(True, f"Opened {url}.")
        if action == "web_search":
            query = str(
                payload.get("query", "") or payload.get("request_text", "")
            ).strip()
            if not query:
                return ToolResult(False, "No search query provided.")
            self._episode(
                "tool_action",
                f"Web searched: {query}",
                tags=["browser", "search"],
                data={"action": action, "query": query},
            )
            self.working.write({"last_tool_action": "web_search"})
            return self._web_search_summary(query)
        if action == "open_code_folder":
            project_path = self._resolve_project_path(
                str(payload.get("project_path", "")).strip()
            )
            if not project_path:
                return ToolResult(False, "No project path was provided.")
            if not Path(project_path).exists():
                return ToolResult(False, f"Project path not found: {project_path}")
            code_cmd = CONFIG.get("apps", {}).get("code") or CONFIG.get("apps", {}).get(
                "vscode"
            )
            if not code_cmd:
                return ToolResult(False, "VS Code command is not configured.")
            parts = shlex.split(code_cmd) + [project_path]
            subprocess.Popen(
                parts, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._episode(
                "tool_action",
                f"Opened code folder: {project_path}",
                tags=["code", "project"],
                data={"action": action, "project_path": project_path},
            )
            self.working.write(
                {
                    "last_tool_action": "open_code_folder",
                    "active_workspace": Path(project_path).name,
                    "active_context_name": Path(project_path).name,
                }
            )
            return ToolResult(
                True,
                f"Opened code folder: {project_path}.",
                {"project_path": project_path},
            )
        if action == "open_terminal_here":
            project_path = self._resolve_project_path(
                str(payload.get("project_path", "")).strip()
            )
            if not project_path:
                return ToolResult(False, "No project path was provided.")
            if not Path(project_path).exists():
                return ToolResult(False, f"Project path not found: {project_path}")
            terminal_cmd = str(CONFIG.get("apps", {}).get("terminal", "")).strip()
            if not terminal_cmd:
                return ToolResult(False, "Terminal command is not configured.")
            terminal_bin = shlex.split(terminal_cmd)[0]
            if terminal_bin == "konsole":
                subprocess.Popen(
                    ["konsole", "--workdir", project_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif terminal_bin == "gnome-terminal":
                subprocess.Popen(
                    ["gnome-terminal", "--working-directory", project_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    shlex.split(terminal_cmd),
                    cwd=project_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self._episode(
                "tool_action",
                f"Opened terminal in: {project_path}",
                tags=["terminal", "project"],
                data={"action": action, "project_path": project_path},
            )
            self.working.write({"last_tool_action": "open_terminal_here"})
            return ToolResult(
                True,
                f"Opened terminal in: {project_path}.",
                {"project_path": project_path},
            )
        if action == "save_context":
            context_name = str(payload.get("context_name", "")).strip()
            project_path = self._resolve_project_path(
                str(payload.get("project_path", "")).strip()
            )
            apps = [
                str(x).strip().lower()
                for x in payload.get("apps", [])
                if str(x).strip()
            ]
            url_keys = [
                str(x).strip().lower()
                for x in payload.get("url_keys", [])
                if str(x).strip()
            ]
            urls = [str(x).strip() for x in payload.get("urls", []) if str(x).strip()]
            notes = str(payload.get("notes", "")).strip()
            tags = [str(x).strip() for x in payload.get("tags", []) if str(x).strip()]
            layout = str(payload.get("layout", "")).strip()
            if not context_name:
                if project_path:
                    context_name = Path(project_path).name
                elif apps:
                    context_name = " ".join(apps[:2]).strip() or "Saved Workspace"
                elif url_keys:
                    context_name = " ".join(url_keys[:2]).strip() or "Saved Workspace"
                elif notes:
                    context_name = notes[:50]
                else:
                    context_name = f"Saved Workspace {time.strftime('%Y-%m-%d %H:%M')}"
            ctx = self.memory.remember_context(
                name=context_name,
                project_path=project_path,
                apps=apps,
                url_keys=url_keys,
                urls=urls,
                notes=notes,
                tags=tags,
                layout=layout,
                source="tool",
            )
            self._episode(
                "tool_action",
                f"Saved context: {ctx['name']}",
                tags=["memory", "context"],
                data={"action": action, "context": ctx},
            )
            self.working.write(
                {
                    "last_tool_action": "save_context",
                    "active_workspace": ctx["name"],
                    "active_context_name": ctx["name"],
                }
            )
            return ToolResult(True, f"Saved context: {ctx['name']}.", {"context": ctx})
        if action == "resume_last_context":
            context_name = str(payload.get("context_name", "")).strip()
            query = str(payload.get("query", "")).strip()
            if context_name:
                ctx = self.memory.get_context(context_name)
            elif query:
                ctx = self.memory.search_best_context(query)
            else:
                ctx = self.memory.get_last_context()
            if not ctx:
                return ToolResult(False, "No saved context was found.")
            current_name = str(
                self.working.read().get("active_context_name", "")
            ).strip()
            if (
                current_name
                and current_name.lower() != str(ctx.get("name", "")).strip().lower()
            ):
                try:
                    self._execute_one({"action": "close_app", "app": "code"})
                    self._execute_one({"action": "close_app", "app": "terminal"})
                except Exception:
                    pass
            result = self._execute_many(self.memory.build_actions_from_context(ctx))
            self.memory.touch_context(str(ctx.get("name", "")))
            self._run_layout_hook(ctx)
            self._episode(
                "tool_action",
                f"Resumed context: {ctx['name']}",
                tags=["memory", "context"],
                data={"action": action, "context": ctx},
            )
            self.working.write(
                {
                    "last_tool_action": "resume_last_context",
                    "active_workspace": ctx["name"],
                    "active_context_name": ctx["name"],
                }
            )
            return ToolResult(
                result.ok,
                f"Resumed context: {ctx['name']}. {result.message}",
                {"context": ctx, "results": (result.data or {}).get("results", [])},
            )
        if action == "save_routine":
            routine_name = str(payload.get("routine_name", "")).strip()
            steps = payload.get("steps", [])
            description = str(payload.get("description", "")).strip()
            tags = [str(x).strip() for x in payload.get("tags", []) if str(x).strip()]
            if not routine_name:
                return ToolResult(False, "A routine name is required.")
            if not isinstance(steps, list) or not steps:
                return ToolResult(False, "A non-empty steps list is required.")
            routine = self.memory.save_routine(
                name=routine_name,
                steps=steps,
                description=description,
                tags=tags,
            )
            self.procedural.save_routine(
                routine_name,
                description=description,
                triggers=[routine_name],
                steps=steps,
                tags=tags,
            )
            self._episode(
                "tool_action",
                f"Saved routine: {routine['name']}",
                tags=["memory", "routine"],
                data={"action": action, "routine": routine},
            )
            self.working.write({"last_tool_action": "save_routine"})
            return ToolResult(
                True, f"Saved routine: {routine['name']}.", {"routine": routine}
            )
        if action == "run_routine":
            routine_name = str(payload.get("routine_name", "")).strip()
            if not routine_name:
                return ToolResult(False, "A routine name is required.")
            routine = self.memory.get_routine(routine_name)
            source = "memory"
            if routine is None:
                proc_routine = self.procedural.get_routine(routine_name)
                if proc_routine:
                    routine = proc_routine
                    source = "procedural"
            if routine is None:
                routines_cfg = CONFIG.get("routines", {})
                q = routine_name.strip().lower().replace("_", " ").replace("-", " ")
                q = " ".join(q.split())
                exact_key = None
                partial_key = None
                for key in routines_cfg.keys():
                    key_norm = key.strip().lower().replace("_", " ").replace("-", " ")
                    key_norm = " ".join(key_norm.split())
                    if key_norm == q:
                        exact_key = key
                        break
                    if q in key_norm and partial_key is None:
                        partial_key = key
                chosen_key = exact_key or partial_key
                if chosen_key:
                    cfg_routine = routines_cfg.get(chosen_key)
                    if isinstance(cfg_routine, dict):
                        routine = cfg_routine
                        source = "config"
                        routine_name = chosen_key
            if routine is None:
                return ToolResult(False, f"Routine not found: {routine_name}")
            steps = routine.get("steps") or routine.get("actions") or []
            if not isinstance(steps, list) or not steps:
                return ToolResult(False, f"Routine has no steps: {routine_name}")
            hosting = self.semantic.get_fact("microschool_hosting")
            if (
                routine_name == "microschool_website_changes"
                and hosting == "cloud_hosted"
            ):
                # Prefer cloud/browser assumptions; keep routine execution but fact is available for future branching
                pass
            result = self._execute_many(steps)
            project_path = self._resolve_project_path(
                str(routine.get("project_path", "")).strip()
            )
            context_name = str(routine.get("context_name", "")).strip() or routine_name
            apps = [
                str(x).strip().lower()
                for x in routine.get("apps", [])
                if str(x).strip()
            ]
            url_keys = [
                str(x).strip().lower()
                for x in routine.get("url_keys", [])
                if str(x).strip()
            ]
            urls = [str(x).strip() for x in routine.get("urls", []) if str(x).strip()]
            notes = str(routine.get("description", "")).strip()
            tags = [str(x).strip() for x in routine.get("tags", []) if str(x).strip()]
            layout = str(routine.get("layout", "")).strip()
            ctx = self.memory.remember_context(
                name=context_name,
                project_path=project_path,
                apps=apps,
                url_keys=url_keys,
                urls=urls,
                notes=notes,
                tags=tags,
                layout=layout,
                source=f"routine:{source}",
            )
            self.memory.touch_routine(routine_name)
            self._run_layout_hook(ctx)
            self._episode(
                "tool_action",
                f"Ran routine: {routine_name}",
                tags=["routine"],
                data={"action": action, "routine_name": routine_name, "source": source},
            )
            self.working.write(
                {
                    "last_tool_action": "run_routine",
                    "active_workspace": context_name,
                    "active_context_name": context_name,
                }
            )
            return ToolResult(
                result.ok,
                f"Ran routine: {routine_name}. {result.message}",
                {
                    "routine": routine_name,
                    "context": ctx,
                    "results": (result.data or {}).get("results", []),
                },
            )
        if action == "list_files":
            folder = (
                str(payload.get("project_path", "")).strip()
                or str(payload.get("path", "")).strip()
            )
            folder = self._resolve_project_path(folder)
            if not folder:
                return ToolResult(False, "No folder path was provided.")
            p = Path(folder)
            if not p.exists() or not p.is_dir():
                return ToolResult(False, f"Folder not found: {folder}")
            items = []
            for child in sorted(p.iterdir()):
                items.append(
                    {
                        "name": child.name,
                        "is_dir": child.is_dir(),
                        "path": str(child),
                    }
                )
            return ToolResult(True, f"Found {len(items)} items.", {"items": items})
        if action == "read_file":
            path = str(payload.get("path", "")).strip()
            if not path:
                return ToolResult(False, "No file path was provided.")
            p = Path(path).expanduser()
            if not p.exists() or not p.is_file():
                return ToolResult(False, f"File not found: {path}")
            text = p.read_text(encoding="utf-8", errors="ignore")
            return ToolResult(
                True, f"Read file: {p.name}", {"path": str(p), "content": text[:12000]}
            )
        if action == "write_file":
            path = str(payload.get("path", "")).strip()
            content = str(payload.get("content", ""))
            if not path:
                return ToolResult(False, "No file path was provided.")
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(True, f"Wrote file: {p.name}", {"path": str(p)})
        if action == "mode_lock_in":
            launched: list[str] = []
            for cmd in CONFIG.get("modes", {}).get("lock_in", []):
                subprocess.Popen(
                    shlex.split(cmd),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                launched.append(shlex.split(cmd)[0])
            self._episode(
                "tool_action",
                "Activated lock in mode.",
                tags=["mode"],
                data={"action": action, "launched": launched},
            )
            return ToolResult(
                True, f"Lock in mode activated. Launched: {', '.join(launched)}."
            )
        if action == "volume_change":
            if not command_exists("amixer"):
                return ToolResult(False, "amixer is not installed.")
            delta = int(payload.get("delta", 0))
            sign = "+" if delta >= 0 else "-"
            run_cmd(["amixer", "-D", "pulse", "sset", "Master", f"{abs(delta)}%{sign}"])
            return ToolResult(True, f"Volume adjusted by {delta}.")
        if action == "volume_set":
            if not command_exists("amixer"):
                return ToolResult(False, "amixer is not installed.")
            value = max(0, min(100, int(payload.get("value", 50))))
            run_cmd(["amixer", "-D", "pulse", "sset", "Master", f"{value}%"])
            return ToolResult(True, f"Volume set to {value} percent.")
        if action == "mute_toggle":
            if not command_exists("amixer"):
                return ToolResult(False, "amixer is not installed.")
            run_cmd(["amixer", "-D", "pulse", "sset", "Master", "toggle"])
            return ToolResult(True, "Mute toggled.")
        if action == "screenshot":
            ok, result = self._capture_screenshot()
            if not ok:
                return ToolResult(False, result)
            return ToolResult(True, f"Screenshot saved to {result}.", {"path": result})
        if action == "tell_time":
            return ToolResult(True, time.strftime("It is %I:%M %p."))
        if action == "projector_on":
            script = Path(CONFIG.get("projector_on_script", "")).expanduser()
            if not script.exists():
                return ToolResult(False, f"Projector on script not found: {script}")
            subprocess.Popen(
                [str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return ToolResult(True, "Projector on sequence started.")
        if action == "projector_off":
            script = Path(CONFIG.get("projector_off_script", "")).expanduser()
            if not script.exists():
                return ToolResult(False, f"Projector off script not found: {script}")
            subprocess.Popen(
                [str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return ToolResult(True, "Projector off sequence started.")
        if action == "sleep":
            run_cmd(["systemctl", "suspend"])
            return ToolResult(True, "Suspending.")
        if action == "restart":
            run_cmd(["systemctl", "reboot"])
            return ToolResult(True, "Restarting.")
        if action == "shutdown":
            run_cmd(["systemctl", "poweroff"])
            return ToolResult(True, "Shutting down.")
        return ToolResult(False, f"Unknown action: {action}")
