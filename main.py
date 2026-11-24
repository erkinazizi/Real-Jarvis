"""JARVIS - main loop.  Run:  python main.py"""
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")   # models are already downloaded: start faster, no HF warning

import asyncio
import re
import signal
import threading
import time
import traceback

import config
import router
from audio import Ears
from brain import Brain
from brain_local import ask_local
from stt import NAME, Transcriber
from tts import Voice
import persona

class _NoUI:
    """Used when the orb is turned off (SHOW_ORB = False)."""
    def set_state(self, state: str) -> None: ...
    def set_level(self, value: float) -> None: ...
    def open_settings(self) -> None: ...
    def close(self) -> None: ...


YES = re.compile(r"\b(yes|yeah|yep|sure|do it|go ahead|proceed|evet|tamam|olur|yap|devam)\b", re.I)


class Jarvis:
    def __init__(self, ui=None):
        print("⏳ Loading models (first run downloads them)...")
        self.ui = ui or _NoUI()
        self.ui.set_state("thinking")                       # orb shows while loading
        self.voice = Voice(on_level=self.ui.set_level)
        self.stt = Transcriber()
        self.ears = Ears(on_level=self.ui.set_level)
        self.ears.spot = self.stt.spot_name                  # wake on a plain "Jarvis" too
        self.brain = Brain(confirm=self.confirm)
        self.lang = config.LANGUAGE
        self.offline_announced = False
        self.speech_q: asyncio.Queue = asyncio.Queue()
        self.t_heard: float | None = None      # when you stopped talking (for latency stats)

    # -- helpers -----------------------------------------------------------
    async def _speak(self, text: str, lang: str) -> bool:
        """Speak one sentence. Returns True if the user started talking over it (barge-in)."""
        if self.voice.interrupted:
            return True
        self._report_latency()
        self.ui.set_state("speaking")
        if not config.BARGE_IN:
            await asyncio.to_thread(self.voice.say, text, lang)
            return False
        stop = threading.Event()
        watcher = asyncio.create_task(asyncio.to_thread(
            self.ears.watch_for_barge_in, self.voice.playback_level, stop, self.voice.interrupt,
            "jarvis" not in text.lower(), lambda audio: self.stt.heard_interrupt(audio, text)))
        try:
            await asyncio.to_thread(self.voice.say, text, lang)
        finally:
            stop.set()
            barged = await watcher or self.voice.interrupted     # (or the orb / menu was clicked)
        if barged:
            print("✋ Interrupted - listening")
        return barged

    def _drop_queued_speech(self) -> None:
        while not self.speech_q.empty():
            self.speech_q.get_nowait()
            self.speech_q.task_done()

    async def _speaker(self) -> None:
        """Plays queued sentences one after another, in the background."""
        while True:
            text, lang = await self.speech_q.get()
            try:
                if await self._speak(text, lang):
                    # you interrupted: drop the rest of the answer and stop Claude
                    self._drop_queued_speech()
                    asyncio.create_task(self.brain.interrupt())
            finally:
                self.speech_q.task_done()
                if self.speech_q.empty():
                    self.ui.set_state("thinking")

    def _report_latency(self) -> None:
        if self.t_heard is not None:
            print(f"⏱  {time.time() - self.t_heard:.2f}s from end of your sentence to Jarvis speaking")
            self.t_heard = None

    async def say_soon(self, text: str, lang: str) -> None:
        """Queue a sentence and return immediately (Claude keeps streaming meanwhile)."""
        if not self.voice.interrupted:
            self.voice.prepare(text, lang)            # render now, while earlier sentences play
            await self.speech_q.put((text, lang))

    async def say(self, text: str, lang: str | None = None) -> None:
        """Say something and wait until it's finished."""
        await self.speech_q.join()
        if await self._speak(text, lang or self.lang):
            self.voice.reset_interrupt()     # what you said is picked up by the next listen()
        self.ui.set_state("thinking")

    def on_click(self) -> None:
        """Orb / menu-bar "Talk to Jarvis": stop talking and listen, or wake up."""
        if self.voice.speaking:
            self.voice.interrupt()
        else:
            self.ears.manual.set()

    async def listen(self, start_timeout: float = 5.0) -> tuple[str, str]:
        self.ui.set_state("listening")
        audio = await asyncio.to_thread(self.ears.record_utterance, start_timeout)
        if audio is None:
            return "", self.lang
        self.ui.set_state("thinking")
        self.t_heard = time.time()
        result = await asyncio.to_thread(self.stt.transcribe, audio)
        print(f"⏱  speech-to-text {time.time() - self.t_heard:.2f}s")
        return result

    async def confirm(self, what: str) -> bool:
        """Ask by voice before a risky action."""
        what = what if len(what) <= 80 else what[:77] + "..."
        q = persona.say("confirm", self.lang, what)
        await self.say(q)
        answer, _ = await self.listen(start_timeout=6.0)
        print(f"🎤 approval: {answer!r}")
        return bool(YES.search(answer))

    # -- one request ---------------------------------------------------------
    async def handle(self, text: str, lang: str) -> bool:
        """Returns False when Jarvis should shut down."""
        self.voice.reset_interrupt()
        m = NAME.match(text)
        if (m and not text[m.end():].strip()) or self.stt.is_stop_only(text):
            # just "Jarvis": Whisper often tags this one word as English -> keep the current language
            print(f"🎤 You: {text}")
            self.ui.set_state("speaking")
            await asyncio.to_thread(self.voice.ack, self.lang)        # "Buyurun efendim?"
            return True
        self.lang = lang
        print(f"🎤 You ({lang}): {text}")

        quick = router.handle(text, lang)
        if quick is router.EXIT:
            await self.say(persona.say("goodbye", lang))
            return False
        if quick is router.SETTINGS:
            self.ui.open_settings()
            await self.say(persona.say("settings", lang))
            return True
        if quick:
            await self.say(quick)
            return True

        try:
            await self.brain.ask(text, lang, lambda t: self.say_soon(t, lang))
            await self.speech_q.join()
            self.offline_announced = False
        except Exception as e:  # network down, CLI not logged in, ...
            print(f"⚠️  Claude failed: {e}")
            if not config.USE_LOCAL_FALLBACK:
                await self.say("Üzgünüm efendim, beynime ulaşamıyorum." if lang == "tr"
                               else "I'm sorry sir, my brain is unreachable.")
                return True
            if not self.offline_announced:
                await self.say("Çevrimdışıyım efendim, yerel beynimi kullanıyorum." if lang == "tr"
                               else "I'm offline, sir. Using my local brain.")
                self.offline_announced = True
            try:
                await self.say(await asyncio.to_thread(ask_local, text, lang))
            except Exception as e2:
                print(f"⚠️  Local brain failed too: {e2}")
                await self.say("Üzgünüm efendim, şu an cevap veremiyorum." if lang == "tr"
                               else "Sorry sir, I can't answer right now.")
            # reconnect Claude for next time
            try:
                await self.brain.stop()
                await self.brain.start()
            except Exception:
                pass
        return True

    # -- main loop -----------------------------------------------------------
    async def run(self) -> None:
        asyncio.create_task(self._speaker())
        try:
            await self.brain.start()
        except Exception as e:
            print(f"⚠️  Could not start Claude ({e}). Running with the local brain only.")
        await self.say(config.GREETING[config.LANGUAGE], config.LANGUAGE)
        self.ui.set_state("hidden")
        print("👂 Say 'Jarvis'...")

        while True:
            hit = await asyncio.to_thread(self.ears.wait_for_wake_word)
            self.voice.reset_interrupt()
            if hit and hit[0]:                           # "Jarvis, saat kaç?" in one breath
                text, lang = hit
                self.t_heard = time.time()
            else:
                self.ui.set_state("listening")
                await asyncio.to_thread(self.voice.ack, self.lang)      # "Buyurun efendim?"
                text, lang = await self.listen()

            # conversation mode: keep listening for follow-ups without the wake word
            while text:
                try:
                    if not await self.handle(text, lang):
                        return
                except Exception:
                    traceback.print_exc()
                text, lang = await self.listen(start_timeout=config.FOLLOW_UP_SEC)
            self.ui.set_state("hidden")
            print("👂 Say 'Jarvis'...")


async def _run(jarvis: Jarvis) -> None:
    try:
        await jarvis.run()
    finally:
        try:
            await jarvis.brain.stop()
        except Exception:
            pass


def main() -> None:
    # Ctrl+C / kill: exit immediately. Use the OS default action, not a Python handler:
    # the orb's Cocoa loop owns the main thread, so Python handlers would never run
    # and `kill` / `pkill` / Ctrl+C would be silently ignored.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    config.LOG_DIR.mkdir(exist_ok=True)
    (config.LOG_DIR / "jarvis.pid").write_text(str(os.getpid()))   # for "Restart Jarvis.command"

    if os.environ.get("JARVIS_NO_UI"):          # terminal only: no orb, no menu-bar icon, no settings window
        asyncio.run(_run(Jarvis()))
        return

    import webview
    from overlay import Overlay

    holder: dict = {}
    overlay = Overlay(on_click=lambda: holder["jarvis"].on_click() if "jarvis" in holder else None)

    def backend() -> None:                      # runs in a background thread
        overlay.ready.wait(timeout=10)
        try:
            holder["jarvis"] = Jarvis(ui=overlay)
            asyncio.run(_run(holder["jarvis"]))
        except Exception:
            traceback.print_exc()
        finally:
            print("👋 Bye.")
            overlay.close()
            os._exit(0)

    webview.start(backend)                     # UI on the main thread (required on macOS)


if __name__ == "__main__":
    main()
