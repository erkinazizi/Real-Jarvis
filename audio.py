"""Microphone input: wake word ("Jarvis" / "Hey Jarvis"), voice-activity-based recording, barge-in."""
import collections
import math
import queue
import threading
import time
import wave
from typing import Callable

import numpy as np
import sounddevice as sd
import torch
from openwakeword.model import Model as WakeModel
from silero_vad import load_silero_vad

import config

SpotFn = Callable[[np.ndarray], "tuple[str, str] | None"]

FRAME = 1280      # 80 ms @ 16 kHz, what openWakeWord expects
VAD_CHUNK = 512   # 32 ms @ 16 kHz, what Silero VAD expects


class Ears:
    def __init__(self, on_level=None):
        self.on_level = on_level or (lambda v: None)   # mic loudness 0..1 -> orb animation
        self.manual = threading.Event()                 # set by clicking the orb = "Hey Jarvis"
        self.wake = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.vad = load_silero_vad()
        self.spot: SpotFn | None = None                 # set by main: Whisper check for a plain "Jarvis"
        self._pending = np.zeros(0, dtype=np.int16)     # leftover samples for the VAD
        self._preroll: list[np.ndarray] = []            # speech heard during barge-in, fed to the next recording
        self._echo: float | None = None                 # how loud Jarvis's own voice comes back into the mic
        self.q: queue.Queue = queue.Queue()
        self.stream: sd.InputStream | None = None
        self.device = ""
        self._last_sound = time.time()                  # last time the mic delivered anything but zeros
        self._last_reopen = 0.0
        self._open_stream()

    # -- microphone device ------------------------------------------------------
    def _open_stream(self, avoid: str = "") -> None:
        """Open the mic: the system default input, unless that's the device that just went silent
        (e.g. AirPods in their case send pure zeros) - then the built-in microphone."""
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        sd._terminate()                  # re-scan devices: PortAudio only sees changes after a restart
        sd._initialize()
        device = None
        if avoid and sd.query_devices(kind="input")["name"] == avoid:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and "macbook" in d["name"].lower():
                    device = i
        self.stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=FRAME, callback=self._on_audio, device=device,
        )
        self.stream.start()
        name = sd.query_devices(device if device is not None else sd.default.device[0])["name"]
        if name != self.device:
            print(f"[mic] using {name}")
        self.device = name
        self._last_sound = self._last_reopen = time.time()

    def _check_mic(self) -> None:
        """If the mic has delivered only exact zeros (or nothing) for 3 s, it's dead: switch."""
        now = time.time()
        if now - self._last_sound > 3 and now - self._last_reopen > 5:
            print(f"[mic] {self.device} is silent - switching microphone")
            try:
                self._open_stream(avoid=self.device)
            except Exception as e:
                print(f"[mic] could not reopen: {e}")
                self._last_reopen = now

    def _on_audio(self, indata, frames, t, status):
        if indata.any():
            self._last_sound = time.time()
        self.q.put(indata[:, 0].copy())

    def _flush(self):
        """Drop audio captured while Jarvis was talking."""
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def _reset_wake(self):
        if hasattr(self.wake, "reset"):
            self.wake.reset()

    def _vad_max(self, frame: np.ndarray) -> float:
        """Speech probability (0..1) of one mic frame (Silero wants 512-sample chunks)."""
        self._pending = np.concatenate([self._pending, frame])
        best = 0.0
        while len(self._pending) >= VAD_CHUNK:
            chunk, self._pending = self._pending[:VAD_CHUNK], self._pending[VAD_CHUNK:]
            best = max(best, self.vad(torch.from_numpy(chunk.astype(np.float32) / 32768.0),
                                      config.SAMPLE_RATE).item())
        return best

    @staticmethod
    def _dock_clicked() -> bool:
        """Jarvis.app touches WAKE_FILE when its Dock icon is clicked while Jarvis is running.
        Only fresh clicks count, so a click made mid-conversation doesn't wake it much later."""
        try:
            fresh = time.time() - config.WAKE_FILE.stat().st_mtime < 3
            config.WAKE_FILE.unlink()
            return fresh
        except FileNotFoundError:
            return False

    def _reset_vad(self) -> None:
        self.vad.reset_states()
        self._pending = np.zeros(0, dtype=np.int16)

    def wait_for_wake_word(self) -> tuple[str, str] | None:
        """Block until "Hey Jarvis", "Jarvis" or an orb click.
        Returns (command, lang) when you said it in one breath ("Jarvis, saat kaç?"), else None."""
        self._flush()
        self._reset_wake()
        self._reset_vad()
        self._preroll = []
        self.manual.clear()
        use_name = config.WAKE_ON_NAME and self.spot is not None
        before = collections.deque(maxlen=4)           # ~0.3 s just before speech starts
        seg: list[np.ndarray] = []
        speaking, run, silence = False, 0, 0.0
        frame_sec = FRAME / config.SAMPLE_RATE
        t_dbg, lvl, peak = time.time(), 0.0, 0.0
        while True:
            if self.manual.is_set() or self._dock_clicked():
                self.manual.clear()
                return None
            self._check_mic()
            try:
                frame = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            scores = self.wake.predict(frame)
            score = max(scores.values()) if scores else 0.0
            if config.DEBUG_WAKE:
                peak = max(peak, score)
                lvl = max(lvl, float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2))))
                if time.time() - t_dbg > 5:
                    print(f"[wake] mic level {lvl:.3f}, hey-jarvis score {peak:.2f} (last 5 s)")
                    t_dbg, lvl, peak = time.time(), 0.0, 0.0
            if score >= config.WAKE_THRESHOLD:
                self._reset_wake()
                return None
            if not use_name:
                continue

            # collect short phrases and ask Whisper whether they start with "Jarvis"
            prob = self._vad_max(frame)
            (seg if speaking else before).append(frame)
            if prob > 0.5:
                run, silence = run + 1, 0.0
                if not speaking and run >= 2:
                    speaking, seg = True, list(before)
            else:
                run = 0
                if speaking:
                    silence += frame_sec
            too_long = speaking and len(seg) * frame_sec > config.NAME_MAX_SEC + 1
            if speaking and (silence >= 0.5 or too_long):
                audio = np.concatenate(seg).astype(np.float32) / 32768.0
                speaking, seg = False, []
                before.clear()
                if config.DEBUG_WAKE:
                    print(f"[wake] phrase {len(audio) / config.SAMPLE_RATE:.1f}s"
                          f"{' (too long, skipped)' if too_long else ''}")
                if not too_long and len(audio) >= 0.3 * config.SAMPLE_RATE:
                    hit = self.spot(audio)
                    if hit is not None:
                        self._reset_wake()
                        return hit
                self._reset_vad()

    def watch_for_barge_in(self, playback_level: Callable[[], float], stop: threading.Event,
                           on_barge: Callable[[], None], use_wake: bool = True) -> bool:
        """Runs while Jarvis speaks. If you start talking (or say "Jarvis"), calls on_barge() and
        returns True; your first words are kept for the next recording. Jarvis's own voice also
        reaches the mic, so speech only counts when it is clearly louder than that echo."""
        self._reset_wake()
        self._reset_vad()
        recent = collections.deque(maxlen=int(1.5 * config.SAMPLE_RATE / FRAME))
        need = max(1, math.ceil(config.BARGE_SPEECH_SEC * config.SAMPLE_RATE / FRAME))
        run, t0, calib = 0, time.time(), 0.0
        while not stop.is_set():
            try:
                frame = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            recent.append(frame)
            rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
            ref = playback_level()

            scores = self.wake.predict(frame)
            # (use_wake=False when Jarvis's own sentence says "Jarvis", so it can't interrupt itself)
            hit = use_wake and bool(scores) and max(scores.values()) >= config.WAKE_THRESHOLD
            prob = self._vad_max(frame)

            # learn the echo level from the start of each sentence (you rarely interrupt that fast)
            if time.time() - t0 < 0.5 and ref > 0.01:
                calib = max(calib, rms / ref)
            elif calib:
                self._echo = calib if self._echo is None else min(0.7 * self._echo + 0.3 * calib,
                                                                   2 * self._echo)
                calib = 0.0
            echo = self._echo if self._echo is not None else 1.0
            loud = rms > max(config.BARGE_MIN_RMS, config.BARGE_ECHO_FACTOR * echo * ref)
            run = run + 1 if (prob > 0.6 and loud) else 0
            if hit or run >= need:
                self._preroll = list(recent)[-(run + 4):]
                self._reset_wake()
                on_barge()
                return True
        return False

    def record_utterance(self, start_timeout: float = 5.0):
        """Record until the user stops talking. Returns float32 audio or None if silent."""
        pre, self._preroll = self._preroll, []           # words spoken over Jarvis (barge-in)
        if not pre:
            self._flush()
        self._reset_vad()
        frames, pending = [], np.zeros(0, dtype=np.int16)
        speech, silence, t0 = False, 0.0, time.time()
        processed, first, last = 0, None, 0     # sample positions of detected speech
        run = 0                                 # consecutive speech chunks
        # tail of "Hey Jarvis" / chime (nothing to skip when we start from barge-in audio)
        skip = 0 if pre else int(config.IGNORE_START_SEC * config.SAMPLE_RATE)

        while True:
            if pre:
                frame = pre.pop(0)
            else:
                try:
                    frame = self.q.get(timeout=1.0)
                except queue.Empty:              # mic stopped delivering (unplugged / AirPods gone)
                    self._check_mic()
                    if time.time() - t0 > max(start_timeout, config.MAX_RECORD_SEC):
                        return None
                    continue
            frames.append(frame)
            rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
            self.on_level(min(1.0, rms * 10))
            pending = np.concatenate([pending, frame])
            while len(pending) >= VAD_CHUNK:
                chunk, pending = pending[:VAD_CHUNK], pending[VAD_CHUNK:]
                prob = self.vad(torch.from_numpy(chunk.astype(np.float32) / 32768.0),
                                config.SAMPLE_RATE).item()
                if processed < skip:
                    processed += VAD_CHUNK
                    continue
                if prob > 0.5:
                    run += 1
                    if run >= config.MIN_SPEECH_CHUNKS:      # ~100 ms of real speech
                        if not speech:
                            first = processed - (run - 1) * VAD_CHUNK
                        speech, silence = True, 0.0
                        last = processed + VAD_CHUNK
                else:
                    run = 0
                    if speech:
                        silence += VAD_CHUNK / config.SAMPLE_RATE
                processed += VAD_CHUNK

            elapsed = time.time() - t0
            if speech and silence >= config.SILENCE_SEC:
                break
            if not speech and elapsed > start_timeout:
                return None
            if elapsed > config.MAX_RECORD_SEC:
                break

        audio = np.concatenate(frames).astype(np.float32) / 32768.0
        # keep only the speech (+0.3 s padding): less noise for Whisper, faster STT
        pad = int(0.3 * config.SAMPLE_RATE)
        audio = audio[max(skip, (first or 0) - pad): last + pad]
        self._save_debug(audio)
        return audio

    @staticmethod
    def _save_debug(audio) -> None:
        """Keep the last recording in logs/last.wav so you can hear what Jarvis heard."""
        config.LOG_DIR.mkdir(exist_ok=True)
        with wave.open(str(config.LOG_DIR / "last.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(config.SAMPLE_RATE)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    # Test: say "Hey Jarvis", then a sentence in Turkish or English.
    from stt import Transcriber
    stt = Transcriber()
    ears = Ears()
    ears.spot = stt.spot_name
    print("👂 Say 'Hey Jarvis'... (Ctrl+C to stop)")
    try:
        while True:
            hit = ears.wait_for_wake_word()
            if hit and hit[0]:
                print(f"[{hit[1]}] {hit[0]!r}  (said together with the name)")
                continue
            beep = 0.2 * np.sin(2 * np.pi * 880 * np.arange(2880) / 24000)
            sd.play(beep.astype(np.float32), 24000)
            sd.wait()
            print("✅ Yes, sir? (speak now)")
            audio = ears.record_utterance()
            if audio is None:
                print("… nothing heard")
                continue
            t1 = time.time()
            text, lang = stt.transcribe(audio)
            print(f"[{lang}] {text!r}   (audio {len(audio) / config.SAMPLE_RATE:.1f}s, STT {time.time() - t1:.2f}s)")
    except KeyboardInterrupt:
        print("\n👋 Bye.")
