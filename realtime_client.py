from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import numpy as np
import orjson
import websockets
from websockets.exceptions import ConnectionClosed

from audio import Speaker, pcm16_16k_to_base64_24k
from config import CONFIG
from tools import ToolRegistry
from utils import log_event, notify


SYSTEM_PROMPT = """
Voice should feel grounded, mature, and composed — never youthful.

Tone:
- Quiet confidence
- Masculine
- Very intelligent

Delivery:
- Minimal upward inflection
- Slight pauses between clauses
- No filler words
- No enthusiasm spikes

Operational rules:
- Never invent Home Assistant script names.
- For any lights, Xbox, projector, TV, media-room, or smart-home request, route to the desktop_action tool and let the deterministic tool layer choose the exact jarvis_* script.
- For any request about the current screen, current tab, current file, or what the user is looking at, use desktop_action with action summarize_screen.
- For search-style requests, current events, near-me queries, or explicit lookups, prefer desktop_action with action web_search.
- For work/project/workspace switching, prefer desktop_action with action smart_action so the local planner can restore or switch workspaces.
- If a tool is needed, first give one short acknowledgment, then call desktop_action.
- Do not pretend something succeeded if the tool says it failed.
""".strip()


class RealtimeJarvisClient:
    def __init__(self, speaker: Speaker, tools: ToolRegistry) -> None:
        self.api_key = CONFIG.get("openai_api_key", "")
        self.model = CONFIG.get("realtime_model", "gpt-realtime")
        self.voice = CONFIG.get("voice", "alloy")
        self.speaker = speaker
        self.tools = tools

        self.ws: websockets.ClientConnection | None = None
        self.connected = False
        self.awaiting_user_audio = False
        self._receiver_task: asyncio.Task | None = None

        self.current_text = ""
        self.busy = False
        self.waiting_for_tool_followup = False
        self.last_cycle_end_at = 0.0
        self._override_handled = False
        self._drop_audio_until = 0.0

    def _project_resume_override(
        self, transcript: str, text: str
    ) -> dict[str, Any] | None:
        known_targets = (
            "jarvis",
            "microschool",
            "tileworld",
            "lumen",
            "truth",
            "daemon",
        )

        projectish = (
            "project" in text
            or "workspace" in text
            or any(token in text for token in known_targets)
        )

        resume_phrases = (
            "continue previous work",
            "continue working on",
            "resume work on",
            "resume working on",
            "resume previous work",
            "restore workspace",
            "restore project",
            "open project",
            "open the project",
            "open my project",
        )

        if projectish and any(phrase in text for phrase in resume_phrases):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "resume_last_context",
                    "query": transcript,
                    "request_text": transcript,
                },
            }

        if projectish and text.startswith("open "):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "resume_last_context",
                    "query": transcript,
                    "request_text": transcript,
                },
            }

        return None

    def _direct_intent_override(self, transcript: str) -> dict[str, Any] | None:
        text = " ".join(str(transcript).strip().lower().split())

        if not text:
            return None

        if any(
            p in text
            for p in [
                "what's on my screen",
                "what is on my screen",
                "what am i looking at",
                "summarize the tab",
                "summarize the screen",
                "current tab",
                "screen right now",
            ]
        ):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "summarize_screen",
                    "request_text": transcript,
                },
            }

        if any(
            k in text
            for k in [
                "lights",
                "light ",
                "xbox",
                "netflix",
                "youtube",
                "spotify",
                "movie mode",
                "night mode",
                "work mode",
                "party mode",
            ]
        ):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "smart_action",
                    "request_text": transcript,
                },
            }

        if any(
            k in text
            for k in [
                "search for",
                "look up",
                "movies playing near me",
                "near me",
                "latest ",
                "today",
                "search the web",
            ]
        ):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "web_search",
                    "query": transcript,
                    "request_text": transcript,
                },
            }

        if any(
            k in text
            for k in [
                "let's get to work",
                "lets get to work",
                "get to work",
                "open my workspace",
                "switch to",
                "work on ",
                "open project",
                "resume ",
                "continue ",
            ]
        ):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "smart_action",
                    "request_text": transcript,
                },
            }

        return None

    async def _run_direct_tool(self, payload: dict[str, Any]) -> None:
        print("Direct tool override:", payload)
        log_event("direct_tool_override", {"payload": payload})

        result = self.tools.execute(payload)
        self._override_handled = True

        followup_actions = {
            "list_windows",
            "get_active_window",
            "desktop_state",
            "tell_time",
            "resume_last_context",
            "summarize_screen",
            "web_search",
            "smart_action",
        }

        action = str(payload.get("action", "")).strip().lower()
        needs_followup = (
            action in followup_actions
            or not result.ok
            or "Awaiting confirmation" in result.message
            or "confirm" in result.message.lower()
            or "error" in result.message.lower()
        )

        if needs_followup:
            await self.send(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(
                                    {
                                        "tool_result": {
                                            "ok": result.ok,
                                            "message": result.message,
                                            "data": result.data or {},
                                        }
                                    }
                                ),
                            }
                        ],
                    },
                }
            )

            await self.send(
                {
                    "type": "response.create",
                    "response": {
                        "modalities": ["audio", "text"],
                        "instructions": (
                            "Briefly report the result in polished British butler style. "
                            "Be precise and do not claim an app or project was already open unless the tool result explicitly shows that."
                        ),
                    },
                }
            )
        else:
            self.busy = False
            self.last_cycle_end_at = time.time()

    async def connect(self) -> None:
        if not self.api_key:
            raise RuntimeError("Missing OpenAI API key.")

        url = f"wss://api.openai.com/v1/realtime?model={self.model}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        self.ws = await websockets.connect(
            url,
            additional_headers=headers,
            max_size=20_000_000,
        )
        self.connected = True
        self._receiver_task = asyncio.create_task(self._receiver())

        await self.send(
            {
                "type": "session.update",
                "session": {
                    "instructions": SYSTEM_PROMPT,
                    "modalities": ["audio", "text"],
                    "voice": self.voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "gpt-4o-mini-transcribe",
                    },
                    "turn_detection": None,
                    "tool_choice": "auto",
                    "tools": self.tools.schemas(),
                },
            }
        )

        log_event("realtime_connected", {"model": self.model, "voice": self.voice})
        print("Realtime connected")

    async def close(self) -> None:
        self.connected = False
        if self._receiver_task:
            self._receiver_task.cancel()
        if self.ws:
            await self.ws.close()
        log_event("realtime_closed", {})

    async def send(self, data: dict[str, Any]) -> None:
        if not self.ws:
            raise RuntimeError("Realtime websocket is not connected.")
        await self.ws.send(orjson.dumps(data).decode())

    async def begin_user_turn(self) -> None:
        self.awaiting_user_audio = True
        log_event("user_turn_started", {})

    async def send_audio(self, chunk: bytes) -> None:
        if not self.awaiting_user_audio:
            return

        arr = np.frombuffer(chunk, dtype=np.int16)
        b64 = pcm16_16k_to_base64_24k(arr)

        await self.send(
            {
                "type": "input_audio_buffer.append",
                "audio": b64,
            }
        )

    async def end_audio(self) -> None:
        if not self.awaiting_user_audio:
            return

        self.awaiting_user_audio = False
        self.current_text = ""
        self.busy = True
        self.waiting_for_tool_followup = False
        self._override_handled = False
        self._drop_audio_until = 0.0

        log_event("user_turn_committed", {})
        print("Committing audio and requesting response")

        await self.send({"type": "input_audio_buffer.commit"})

    async def _handle_tool_call(self, event: dict[str, Any]) -> None:
        try:
            args = json.loads(event.get("arguments", "{}"))
        except Exception:
            args = {}

        print("Tool call:", args)
        log_event("tool_call_received", {"args": args})

        result = self.tools.execute(args)

        await self.send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": event.get("call_id"),
                    "output": json.dumps(
                        {
                            "ok": result.ok,
                            "message": result.message,
                            "data": result.data or {},
                        }
                    ),
                },
            }
        )

        followup_actions = {
            "list_windows",
            "get_active_window",
            "desktop_state",
            "tell_time",
            "resume_last_context",
            "summarize_screen",
            "web_search",
            "smart_action",
        }

        tool_action = str(args.get("action", "")).strip().lower()

        needs_followup = (
            tool_action in followup_actions
            or not result.ok
            or "Awaiting confirmation" in result.message
            or "confirm" in result.message.lower()
            or "error" in result.message.lower()
        )

        if needs_followup:
            self.waiting_for_tool_followup = True
            await self.send(
                {
                    "type": "response.create",
                    "response": {
                        "modalities": ["audio", "text"],
                        "instructions": (
                            "Briefly report the result in polished British butler style. "
                            "Natural Oxford accent, male, early middle-aged, warm and controlled. "
                            "Do not add filler. "
                            "Do not claim something is already open unless the tool result explicitly says so."
                        ),
                    },
                }
            )
        else:
            self.waiting_for_tool_followup = False
            self.busy = False
            self.last_cycle_end_at = time.time()

    async def _receiver(self) -> None:
        assert self.ws is not None

        try:
            while self.connected:
                raw = await self.ws.recv()
                event = json.loads(raw)
                event_type = event.get("type", "")
                log_event("realtime_event", {"type": event_type})

                if event_type == "error":
                    notify(f"Realtime error: {event}")
                    self.busy = False
                    self.speaker.finish_realtime()
                    self.last_cycle_end_at = time.time()
                    continue

                if (
                    event_type
                    == "conversation.item.input_audio_transcription.completed"
                ):
                    transcript = event.get("transcript", "")
                    if transcript:
                        notify(f"Heard: {transcript}")

                        override = self._direct_intent_override(transcript)
                        if override and override.get("type") == "direct_tool":
                            self.awaiting_user_audio = False
                            self.busy = True
                            await self._run_direct_tool(override["payload"])
                            continue

                    if not self._override_handled:
                        await self.send(
                            {
                                "type": "response.create",
                                "response": {
                                    "modalities": ["audio", "text"],
                                    "instructions": (
                                        "Respond as Jarvis. "
                                        "Never invent Home Assistant script names. "
                                        "For lights, Xbox, and smart-home requests, call desktop_action and let the deterministic tool layer choose the exact jarvis_* script. "
                                        "For current screen or tab understanding, call desktop_action with summarize_screen. "
                                        "For search and near-me lookups, call desktop_action with web_search. "
                                        "For work/project switching, call desktop_action with smart_action. "
                                        "If the user requested multiple actions, send a single desktop_action call using an actions array."
                                    ),
                                },
                            }
                        )
                    continue

                if event_type in {"response.text.delta", "response.output_text.delta"}:
                    delta = event.get("delta", "")
                    if delta:
                        self.current_text += delta
                    continue

                if event_type == "response.audio.delta":
                    if time.time() < self._drop_audio_until:
                        continue
                    audio_b64 = event.get("delta", "")
                    if audio_b64:
                        pcm = base64.b64decode(audio_b64)
                        await asyncio.to_thread(self.speaker.play_pcm_chunk, pcm)
                    continue

                if event_type == "response.audio.done":
                    await asyncio.to_thread(self.speaker.finish_realtime)
                    continue

                if event_type == "response.function_call_arguments.done":
                    await self._handle_tool_call(event)
                    continue

                if event_type == "response.done":
                    self.waiting_for_tool_followup = False
                    self.busy = False
                    self._drop_audio_until = 0.0
                    self.last_cycle_end_at = time.time()
                    continue

        except asyncio.CancelledError:
            pass
        except ConnectionClosed as e:
            notify(f"Realtime connection closed: {e}")
            log_event("realtime_connection_closed", {"error": str(e)})
            self.busy = False
            self.speaker.finish_realtime()
            self.last_cycle_end_at = time.time()
        except Exception as e:
            notify(f"Realtime receiver error: {e}")
            log_event("realtime_receiver_error", {"error": str(e)})
            print("Receiver exception:", repr(e))
            self.busy = False
            self.speaker.finish_realtime()
            self.last_cycle_end_at = time.time()
