"""Text-to-speech: the macOS system voice (e.g. Siri Voice 2) for Turkish and English, played
directly with `say` (Siri voices can't be rendered to a file), stoppable mid-sentence."""
import math
import random
import re
import subprocess
import tempfile
import threading
import time
import wave
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import sounddevice as sd

import config


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)        # drop code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)       # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#>|~]", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


Audio = tuple[np.ndarray, int]        # float32 samples, sample rate


class Voice:
    def __init__(self, on_level=None):
        self.on_level = on_level or (lambda v: None)    # voice loudness 0..1 -> orb animation
        self._interrupt = threading.Event()
        self._level = 0.0                                # loudness of what is playing right now
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._cache: dict[tuple[str, str], Future] = {}
        self._tmp = Path(tempfile.mkdtemp(prefix="jarvis-tts-"))

        self.tr_voice = config.TR_MAC_VOICE or self._best_mac_voice("tr_TR") or "system"
        self.en_voice = config.EN_MAC_VOICE or "system"
        print(f"[tts] voices: tr={self.tr_voice}, en={self.en_voice if config.EN_ENGINE == 'mac' else 'kokoro'}")

        self.kokoro = None
        if config.EN_ENGINE == "kokoro":                # optional British Kokoro voice for English
            from kokoro import KPipeline
            self.kokoro = KPipeline(lang_code="b", repo_id="hexgrad/Kokoro-82M")

        self._proc: subprocess.Popen | None = None

    # -- interrupt (barge-in) ----------------------------------------------------
    @property
    def interrupted(self) -> bool:
        return self._interrupt.is_set()

    def interrupt(self) -> None:
        """Stop speaking now (called from the barge-in watcher)."""
        self._interrupt.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def reset_interrupt(self) -> None:
        self._interrupt.clear()

    def playback_level(self) -> float:
        """Loudness of Jarvis's voice right now (barge-in uses it to ignore its own echo)."""
        return self._level

    # -- rendering ----------------------------------------------------------------
    @staticmethod
    def _best_mac_voice(locale: str) -> str | None:
        """Best installed macOS voice for a locale: Premium > Enhanced > normal."""
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        except FileNotFoundError:
            return None
        voices = [m.group(1).strip() for line in out.splitlines()
                  if (m := re.match(r"^(.+?)\s{2,}" + locale + r"\b", line))]
        rank = lambda v: 0 if "Premium" in v else 1 if "Enhanced" in v else 2
        return sorted(voices, key=rank)[0] if voices else None

    def _render_mac(self, text: str, voice: str, rate: int) -> Audio | None:
        out = self._tmp / f"{threading.get_ident()}-{time.time_ns()}.wav"
        cmd = ["say", "-r", str(rate), "-o", str(out), "--file-format=WAVE", "--data-format=LEI16@22050", text]
        if voice and voice != "system":
            cmd[1:1] = ["-v", voice]
        subprocess.run(cmd, check=False, capture_output=True)
        try:
            with wave.open(str(out), "rb") as w:
                sr = w.getframerate()
                data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            return data.astype(np.float32) / 32768.0, sr
        except Exception as e:
            print(f"[tts] say failed: {e}")
            return None
        finally:
            out.unlink(missing_ok=True)

    def _render_kokoro(self, text: str) -> Audio | None:
        parts = []
        for _, _, audio in self.kokoro(text, voice=config.EN_VOICE, speed=1.05):
            if audio is not None:
                parts.append(np.asarray(audio.numpy() if hasattr(audio, "numpy") else audio, dtype=np.float32))
        return (np.concatenate(parts), 24000) if parts else None

    def _render(self, text: str, lang: str) -> Audio | None:
        text = clean_for_speech(text)
        if not text:
            return None
        if lang != "tr" and self.kokoro:
            return self._render_kokoro(text)
        if lang == "tr":
            return self._render_mac(text, self.tr_voice, config.TR_MAC_RATE)
        return self._render_mac(text, self.en_voice, config.EN_MAC_RATE)

    def prepare(self, text: str, lang: str) -> None:
        """Start rendering a sentence in the background (Kokoro only; `say` needs no rendering)."""
        key = (text, lang)
        if self.kokoro and lang != "tr" and key not in self._cache:
            self._cache[key] = self._pool.submit(self._render, text, lang)

    # -- playback -----------------------------------------------------------------
    def _play(self, audio: np.ndarray, sr: int) -> None:
        """Play audio; report loudness to the orb; stop at once if interrupted."""
        if self.interrupted:
            return
        sd.play(audio, sr)
        t0, win = time.time(), int(sr * 0.05)
        try:
            while True:
                if self.interrupted:
                    sd.stop()
                    break
                i = int((time.time() - t0) * sr)
                if i >= len(audio):
                    break
                chunk = audio[i:i + win]
                self._level = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
                self.on_level(min(1.0, self._level * 5))
                time.sleep(0.02)
            if not self.interrupted:
                sd.wait()
        finally:
            self._level = 0.0

    def _say_mac(self, text: str, lang: str) -> None:
        """Speak with the macOS voice exactly as System Settings plays it; stoppable."""
        voice = self.tr_voice if lang == "tr" else self.en_voice
        rate = config.TR_MAC_RATE if lang == "tr" else config.EN_MAC_RATE
        cmd = ["say", "-r", str(rate), text]
        if voice and voice != "system":
            cmd[1:1] = ["-v", voice]
        self._proc = subprocess.Popen(cmd)
        t0 = time.time()
        try:
            while self._proc.poll() is None:
                if self.interrupted:
                    self._proc.terminate()
                    break
                t = time.time() - t0            # no audio samples here: animate a soft "talk" rhythm
                lvl = 0.35 + 0.3 * abs(math.sin(t * 9)) * abs(math.sin(t * 2.3))
                self._level = 0.1               # rough loudness for the barge-in echo check
                self.on_level(lvl)
                time.sleep(0.03)
        finally:
            self._level = 0.0
            self._proc = None

    def say(self, text: str, lang: str = "en") -> None:
        if self.interrupted:
            return
        if not (self.kokoro and lang != "tr"):
            clean = clean_for_speech(text)
            if clean:
                print(f"🤖 Jarvis: {clean}")
                self._say_mac(clean, lang)
            return
        fut = self._cache.pop((text, lang), None)
        audio = fut.result() if fut else self._render(text, lang)
        if audio:
            print(f"🤖 Jarvis: {clean_for_speech(text)}")
            self._play(*audio)

    def ack(self, lang: str = "en") -> None:
        """Instant spoken reply to the wake word ("Buyurun efendim?" / "Yes, sir?")."""
        options = config.WAKE_REPLIES.get(lang) or config.WAKE_REPLIES.get("en") or []
        if options:
            self._say_mac(random.choice(options), lang)
        else:
            self.chime()

    def chime(self) -> None:
        t = np.linspace(0, 0.12, int(24000 * 0.12), endpoint=False)
        tone = 0.25 * np.sin(2 * np.pi * 880 * t) * np.hanning(len(t))
        sd.play(tone.astype(np.float32), 24000)
        sd.wait()


if __name__ == "__main__":
    v = Voice()
    v.ack("tr")
    v.say("Good evening, sir. All systems are online.", "en")
    v.say("İyi akşamlar efendim. Tüm sistemler çalışıyor.", "tr")
