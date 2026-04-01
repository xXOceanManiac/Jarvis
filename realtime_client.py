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

You are not acting. You are naturally this person.
Maintain the same voice identity strictly.
Do not drift in age, tone, or accent.
Voice must remain mature, composed, and subtly British throughout.

Operational rules:
- If the user refers to the current screen, current app, current tab, what they are looking at, or something ambiguous like "do this here", inspect desktop state first.
- Before deciding that a project or workspace is already open, inspect desktop state in the current turn. Never assume it from memory alone.
- If the user asks to continue previous work, resume yesterday, same as before, continue a project, restore a workspace, or open a known project, prefer action "resume_last_context".
- If the user asks for a known workflow, named setup, workspace, or routine, prefer action "run_routine" before any other action.
- If the user asks to turn on a movie, watch a movie, start movie mode, or set a movie vibe, use action "run_ha_script" with script_name "movie_mode_full".
- If the user asks to open Netflix on Xbox, use action "run_ha_script" with script_name "netflix_on_xbox".
- For Xbox, TV, lights, movie scenes, or smart-home commands, prefer action "run_ha_script" over open_app, open_url_key, open_url_raw, web_search, or generic desktop actions.
- If the user asks about open apps, windows, focus, or what is on screen, call desktop_action first.
- Use action "list_windows" for open apps or windows.
- Use action "get_active_window" for focused app.
- Use action "desktop_state" for what is on screen or when screen context matters.
- If the request needs a tool, first give one short acknowledgment, then call desktop_action.
- If the user requested multiple actions, send a single desktop_action call using an "actions" array.
- Do not add a closing flourish after a successful action.
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

        movie_phrases = {
            "turn on the movie",
            "turn on a movie",
            "start movie mode",
            "movie mode",
            "start movie mode on xbox",
            "movie mode on xbox",
            "watch a movie",
            "put on a movie",
            "lets watch a movie",
        }

        netflix_phrases = {
            "open netflix on xbox",
            "start netflix on xbox",
            "netflix on xbox",
        }

        screen_phrases = {
            "what's on my screen",
            "what is on my screen",
            "what am i looking at",
            "what's in front of me",
            "what is in front of me",
            "what screen am i on",
        }

        if any(p in text for p in movie_phrases):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "run_ha_script",
                    "script_name": "movie_mode_full",
                    "request_text": transcript,
                },
            }

        if any(p in text for p in netflix_phrases):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "run_ha_script",
                    "script_name": "netflix_on_xbox",
                    "request_text": transcript,
                },
            }

        if "what apps do i have open" in text or "what do i have open" in text:
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "list_windows",
                    "request_text": transcript,
                },
            }

        if "what am i focused on" in text or "what app am i in" in text:
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "get_active_window",
                    "request_text": transcript,
                },
            }

        if any(p in text for p in screen_phrases):
            return {
                "type": "direct_tool",
                "payload": {
                    "action": "desktop_state",
                    "request_text": transcript,
                },
            }

        project_override = self._project_resume_override(transcript, text)
        if project_override:
            return project_override

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
                                        "If the user is asking about open apps, active focus, current screen context, a routine, or previous work, "
                                        "use desktop_action first rather than answering from memory. "
                                        "Before deciding a project is already open, inspect desktop state in this turn. "
                                        "If the request needs a tool, first give one short acknowledgment, then call desktop_action. "
                                        "If the user requested multiple actions, send a single desktop_action call using an 'actions' array. "
                                        "Do not add any closing line after a successful action."
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
