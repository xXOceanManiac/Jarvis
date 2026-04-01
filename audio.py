from __future__ import annotations

import base64
import queue
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import audioop
import numpy as np
import sounddevice as sd

from config import AUDIO_DIR, CACHE_DIR, CONFIG
from utils import log_event

import base64
import numpy as np
import resampy


def pcm16_16k_to_base64_24k(audio_16k: np.ndarray) -> str:
    """
    Convert 16kHz int16 PCM → 24kHz int16 PCM → base64 string
    Required by OpenAI realtime API.
    """
    if audio_16k.size == 0:
        return ""

    # Convert to float for resampling
    audio_float = audio_16k.astype(np.float32) / 32768.0

    # Resample 16k → 24k
    audio_24k = resampy.resample(audio_float, 16000, 24000)

    # Back to int16
    audio_int16 = (audio_24k * 32768.0).astype(np.int16)

    # Encode base64
    return base64.b64encode(audio_int16.tobytes()).decode("utf-8")


class MicRecorder:
    def __init__(self, samplerate: int = 16000, blocksize: int = 1280, device=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.device = device

        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=512)
        self.stream: sd.InputStream | None = None

    def start(self) -> None:
        self.stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            blocksize=self.blocksize,
            callback=self._callback,
            device=self.device,
        )
        self.stream.start()
        log_event("mic_started", {"samplerate": self.samplerate, "blocksize": self.blocksize})

    def stop(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        log_event("mic_stopped", {})

    def _callback(self, indata, frames, time_info, status):
        if status:
            print("Mic status:", status)

        mono = np.array(indata[:, 0], dtype=np.int16)
        try:
            self.q.put_nowait(mono)
        except queue.Full:
            pass

    def read_chunk(self, timeout=0.1):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


class Speaker:
    def __init__(
        self,
        samplerate: int = 24000,
        state_callback: Callable[[str], None] | None = None,
        blocksize: int = 2048,
    ):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.state_callback = state_callback

        self.is_speaking = False
        self.last_audio_end_at = 0.0

        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()

    def _set_state(self, state: str) -> None:
        if self.state_callback:
            try:
                self.state_callback(state)
            except Exception:
                pass

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return

        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            blocksize=self.blocksize,
        )
        self._stream.start()

    def start_realtime(self) -> None:
        with self._lock:
            self._ensure_stream()
            if not self.is_speaking:
                self.is_speaking = True
                self._set_state("speaking")

    def play_pcm_chunk(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return

        with self._lock:
            self._ensure_stream()
            if not self.is_speaking:
                self.is_speaking = True
                self._set_state("speaking")

            audio_np = np.frombuffer(pcm_bytes, dtype=np.int16)
            if audio_np.size > 0:
                self._stream.write(audio_np)

    def finish_realtime(self) -> None:
        with self._lock:
            self.is_speaking = False
            self.last_audio_end_at = time.time()
            self._set_state("idle")

    def stop(self):
        with self._lock:
            sd.stop()
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            self.is_speaking = False
            self.last_audio_end_at = time.time()
            self._set_state("idle")

    def play_wav_file(self, path: str | Path) -> None:
        wav_path = Path(path).expanduser()
        with wave.open(str(wav_path), "rb") as wf:
            data = wf.readframes(wf.getnframes())
            audio_np = np.frombuffer(data, dtype=np.int16)

        with self._lock:
            self._ensure_stream()
            self.is_speaking = True
            self._set_state("speaking")
            try:
                self._stream.write(audio_np)
            finally:
                self.is_speaking = False
                self.last_audio_end_at = time.time()
                self._set_state("idle")

    def speak_text(self, text: str) -> None:
        raise RuntimeError("Local TTS is disabled. Use realtime model audio instead.")


class WakeAcknowledger:
    def __init__(self, speaker: Speaker) -> None:
        self.speaker = speaker
        self.responses = [
            "At your service, sir.",
            "Yes, sir.",
            "Ready, sir.",
        ]
        self._idx = 0
        self._lock = threading.Lock()

    def next_phrase(self) -> tuple[int, str]:
        with self._lock:
            idx = self._idx % len(self.responses)
            phrase = self.responses[idx]
            self._idx += 1
        return idx, phrase

    def play_next(self) -> str:
        idx, phrase = self.next_phrase()
        wav_path = CACHE_DIR / f"wake_{idx}.wav"

        if wav_path.exists():
            self.speaker.play_wav_file(wav_path)
            log_event("wake_ack_played", {"phrase": phrase, "path": str(wav_path)})
            return phrase

        print(f"[Jarvis Wake Missing] {wav_path}")
        log_event("wake_ack_missing_wav", {"phrase": phrase, "path": str(wav_path)})
        return phrase