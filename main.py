from __future__ import annotations

import asyncio
import time

import numpy as np

from audio import MicRecorder, Speaker
from config import CONFIG
from ptt import PushToTalkController
from realtime_client import RealtimeJarvisClient
from tools import ToolRegistry
from utils import log_event, notify
from visuals import VisualStateController
from wakeword import WakeWordDetector


class JarvisV2:
    def __init__(self) -> None:
        self.sample_rate_in = int(CONFIG.get("sample_rate_in", 16000))
        self.sample_rate_out = int(CONFIG.get("sample_rate_out", 24000))
        self.speaker_blocksize = int(CONFIG.get("speaker_blocksize", 2048))
        self.max_turn_seconds = float(CONFIG.get("max_turn_seconds", 12.0))
        self.mic_device = CONFIG.get("mic_device")

        self.wake_word_min_listen_seconds = float(
            CONFIG.get("wake_word_min_listen_seconds", 0.90)
        )
        self.wake_word_end_silence_seconds = float(
            CONFIG.get("wake_word_end_silence_seconds", 1.10)
        )
        self.wake_word_energy_threshold = float(
            CONFIG.get("wake_word_energy_threshold", 550.0)
        )

        self.visuals = VisualStateController()
        self.speaker = Speaker(
            samplerate=self.sample_rate_out,
            blocksize=self.speaker_blocksize,
            state_callback=self.visuals.set_state,
        )
        self.mic = MicRecorder(
            samplerate=self.sample_rate_in,
            device=self.mic_device,
        )
        self.tools = ToolRegistry()
        self.client = RealtimeJarvisClient(self.speaker, self.tools)

        # Wake word is now optional. The detector always exists, but it can report
        # "not ready" without breaking the rest of Jarvis.
        self.wakeword = WakeWordDetector()

        self.running = True
        self.user_turn_active = False
        self.user_turn_source = ""
        self.user_turn_started_at = 0.0
        self.last_voice_activity_at = 0.0
        self.loop: asyncio.AbstractEventLoop | None = None

        self.ptt = PushToTalkController(
            on_activated=self._on_ptt_activated,
            on_released=self._on_ptt_released,
        )

    async def startup(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.client.connect()
        self.mic.start()
        self.ptt.start()
        self._set_idle_visual_state()

        status_bits = []
        if self.wakeword.is_ready:
            status_bits.append("wake word armed")
        else:
            status_bits.append("PTT ready")

        notify(f"Jarvis v2 started. {' | '.join(status_bits)}")
        log_event(
            "jarvis_started",
            {
                "wake_word_ready": self.wakeword.is_ready,
                "wake_word_error": self.wakeword.error,
            },
        )

    async def shutdown(self) -> None:
        self.running = False
        self.ptt.stop()
        self.mic.stop()
        self.speaker.stop()
        self.wakeword.close()
        await self.client.close()
        self.visuals.set_state("idle")
        log_event("jarvis_stopped", {})

    def _set_idle_visual_state(self) -> None:
        if not self.speaker.is_speaking and not self.client.busy:
            self.visuals.set_state("armed")
        else:
            self.visuals.set_state("idle")

    def _chunk_rms(self, chunk: np.ndarray) -> float:
        if chunk is None or chunk.size == 0:
            return 0.0
        arr = chunk.astype(np.float32)
        return float(np.sqrt(np.mean(arr * arr)))

    def _on_ptt_activated(self) -> None:
        if not self.loop:
            return
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._begin_turn("ptt"))
        )

    def _on_ptt_released(self) -> None:
        if not self.loop:
            return
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._commit_turn("ptt_release"))
        )

    async def _begin_turn(self, source: str) -> None:
        if self.user_turn_active:
            return

        if self.speaker.is_speaking or self.client.busy:
            return

        self.mic.drain()
        await self.client.begin_user_turn()

        self.user_turn_active = True
        self.user_turn_source = source
        self.user_turn_started_at = time.time()
        self.last_voice_activity_at = self.user_turn_started_at

        self.visuals.set_state("listening")
        if source == "wakeword":
            notify("Wake word detected")
            log_event("wakeword_turn_started", {})
        else:
            notify("Listening")
            log_event("ptt_turn_started", {})

    async def _commit_turn(self, reason: str) -> None:
        if not self.user_turn_active:
            return

        source = self.user_turn_source
        self.user_turn_active = False
        self.user_turn_source = ""
        self.visuals.set_state("processing")

        await self.client.end_audio()
        self.mic.drain()

        log_event(
            "turn_committed",
            {
                "reason": reason,
                "source": source,
            },
        )

    async def _handle_active_turn(self, chunk: np.ndarray) -> None:
        if not self.user_turn_active:
            return

        if self.client.busy:
            return

        await self.client.send_audio(chunk.tobytes())

        now = time.time()
        rms = self._chunk_rms(chunk)
        if rms >= self.wake_word_energy_threshold:
            self.last_voice_activity_at = now

        if (now - self.user_turn_started_at) >= self.max_turn_seconds:
            await self._commit_turn("max_turn_seconds")
            return

        if self.user_turn_source == "wakeword":
            elapsed = now - self.user_turn_started_at
            silent_for = now - self.last_voice_activity_at
            if (
                elapsed >= self.wake_word_min_listen_seconds
                and silent_for >= self.wake_word_end_silence_seconds
            ):
                await self._commit_turn("wakeword_silence")
                return

    async def _handle_idle_chunk(self, chunk: np.ndarray) -> None:
        if self.speaker.is_speaking or self.client.busy:
            return

        if self.wakeword.is_ready and self.wakeword.process(chunk):
            await self._begin_turn("wakeword")

    async def run(self) -> None:
        await self.startup()

        try:
            while self.running:
                chunk = self.mic.read_chunk(timeout=0.05)

                if chunk is None:
                    await asyncio.sleep(0.01)
                    continue

                if self.user_turn_active:
                    await self._handle_active_turn(chunk)
                else:
                    await self._handle_idle_chunk(chunk)
                    if (
                        not self.speaker.is_speaking
                        and not self.client.busy
                        and not self.user_turn_active
                    ):
                        self._set_idle_visual_state()

        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()


async def amain() -> None:
    app = JarvisV2()
    await app.run()


if __name__ == "__main__":
    asyncio.run(amain())
