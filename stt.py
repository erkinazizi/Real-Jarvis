"""Local speech-to-text with Whisper on MLX (runs on the M4 GPU)."""
import re

import mlx_whisper
import numpy as np

import config

# "Jarvis" at the start of a phrase, as Whisper may spell it in English or Turkish
NAME = re.compile(r"^\W*(?:hey|hi|ey|hay)?[\s,]*(?:j|c|ç|dj|g|ch)[aeə]r?[vw][iıeüu][sşz](?![\w'’])[\s,.!?:]*", re.I)

# Whisper sometimes "hears" these in silence / noise
HALLUCINATIONS = re.compile(
    r"^(thank you\.?|thanks for watching\.?|you\.?|altyazı.*|abone ol.*|\.+)$", re.I
)


# words that make Jarvis stop talking (said over its voice), besides its name
STOP_WORDS = re.compile(r"\b(stop|wait|enough|quiet|shut up|hold on|dur|bekle|sus|yeter|tamam tamam|kes)\b", re.I)
NAME_ANYWHERE = re.compile(r"(?:^|\W)(?:j|c|ç|dj|g|ch)[aeə]r?[vw][iıeüu][sşz](?![\w])", re.I)


class Transcriber:
    def __init__(self):
        # warm-up (both code paths) so the first real command is fast
        silence = np.zeros(config.SAMPLE_RATE, dtype=np.float32)
        self._run(silence, "en")
        self._run(silence)

    def _run(self, audio, language=None, prompt: str | None = "Jarvis, Hey Jarvis."):
        return mlx_whisper.transcribe(
            audio, path_or_hf_repo=config.WHISPER_MODEL,
            language=language, condition_on_previous_text=False, verbose=None,
            temperature=0.0,                      # no random retries -> faster, fewer loops
            no_speech_threshold=0.6,
            initial_prompt=prompt,                # helps Whisper spell "Jarvis" right
        )

    @staticmethod
    def _dedupe(text: str) -> str:
        """Whisper sometimes repeats the same sentence in a loop; keep one copy."""
        out: list[str] = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if sent and (not out or sent.lower() != out[-1].lower()):
                out.append(sent)
        return " ".join(out)

    def transcribe(self, audio) -> tuple[str, str]:
        """Returns (text, lang) where lang is 'tr' or 'en'."""
        result = self._run(audio)
        lang = result.get("language", "en")
        if lang not in ("tr", "en"):          # Jarvis only speaks TR / EN
            lang = config.LANGUAGE
            result = self._run(audio, lang)
        text = self._dedupe(result.get("text", "").strip())
        if len(text) < 2 or HALLUCINATIONS.match(text):
            return "", lang
        return text, lang

    def heard_interrupt(self, audio, own_text: str = "") -> bool:
        """While Jarvis talks: did the user say "Jarvis" or a stop word over it?
        Words that are in Jarvis's own sentence don't count (its voice comes back into the mic)."""
        result = self._run(audio, prompt=None)
        text = result.get("text", "").strip()
        own = own_text.lower()
        name = NAME_ANYWHERE.search(text) and not NAME_ANYWHERE.search(own)
        stop = STOP_WORDS.search(text)
        stop = stop and stop.group(0).lower() not in own
        if config.DEBUG_WAKE and text:
            print(f"[barge] heard {text!r} -> {'STOP' if (name or stop) else 'ignored'}")
        return bool(name or stop)

    @staticmethod
    def is_stop_only(text: str) -> bool:
        """'Dur.' / 'Stop!' / 'Jarvis, bekle' - nothing to do except listen."""
        rest = STOP_WORDS.sub("", NAME.sub("", text, count=1)).strip(" ,.!?")
        return bool(STOP_WORDS.search(text)) and len(rest) < 3

    def spot_name(self, audio) -> tuple[str, str] | None:
        """Was this short phrase addressed to Jarvis?  Returns (command after the name, lang) or None.
        No "Jarvis" prompt here, so Whisper can't invent the name out of noise."""
        result = self._run(audio, prompt=None)
        lang = result.get("language", config.LANGUAGE)
        lang = lang if lang in ("tr", "en") else config.LANGUAGE
        text = result.get("text", "").strip()
        m = NAME.match(text)
        if config.DEBUG_WAKE:
            print(f"[wake] heard {text!r} ({lang}) -> {'NAME' if m else 'ignored'}")
        if not m:
            return None
        rest = text[m.end():].strip()
        return (rest if len(rest) >= 3 and not HALLUCINATIONS.match(rest) else ""), lang


if __name__ == "__main__":
    for t in ["Jarvis.", "Jarvis, saat kaç?", "Hey Jarvis, open Safari", "Carvis bana hava durumunu söyle",
              "Cervis", "Bugün hava güzel", "Jarvis'e söyle"]:
        m = NAME.match(t)
        print(f"{t!r:45} -> {(t[m.end():].strip() if m else None)!r}")
