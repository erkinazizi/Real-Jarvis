"""Jarvis settings: the list of editable options, saving them to settings.json, and the settings window.

config.py holds the defaults; anything saved here (settings.json) overrides them at startup.
Open the window from the menu-bar icon, by saying "open settings" / "ayarları aç",
or on its own with:  python settings.py
"""
import json
import os
import re
import subprocess
import sys
import threading

import config

SETTINGS_FILE = config.SETTINGS_FILE
HTML = config.BASE_DIR / "ui" / "settings.html"

MODELS = [
    ["haiku", "Claude Haiku — fastest"],
    ["sonnet", "Claude Sonnet — smarter, a bit slower"],
    ["opus", "Claude Opus — smartest, slowest"],
]
KOKORO_VOICES = ["bm_george", "bm_lewis", "bm_fable", "bm_daniel", "bf_emma", "bf_isabella",
                 "am_michael", "am_adam", "af_heart", "af_bella"]

# key, section, label, type, extra
SCHEMA: list[dict] = [
    # General
    dict(key="USER_NAME", section="General", label="Your name", type="text",
         help="How Jarvis refers to you."),
    dict(key="LANGUAGE", section="General", label="Default language", type="segmented",
         options=[["tr", "Türkçe"], ["en", "English"]],
         help="Used for greetings and when the spoken language is unclear."),
    # Personality
    dict(key="TONE", section="Personality", label="Tone", type="segmented",
         options=[["formal", "Formal"], ["polite", "Polite"], ["friendly", "Friendly"], ["casual", "Casual"]],
         help="Formal: a British butler who calls you “sir” / “efendim”. Casual: talks like a close friend "
              "and uses your first name (“sen” in Turkish)."),
    dict(key="HUMOR", section="Personality", label="Humour", type="segmented",
         options=[["none", "None"], ["light", "Light"], ["witty", "Witty"]]),
    # Voice
    dict(key="TR_MAC_VOICE", section="Voice", label="Turkish voice", type="voice", lang="tr",
         help="“System voice” = the voice chosen in System Settings › Accessibility › Spoken Content (e.g. Siri Voice 2)."),
    dict(key="TR_MAC_RATE", section="Voice", label="Turkish speed", type="range", min=120, max=280, step=5,
         unit="words/min"),
    dict(key="EN_ENGINE", section="Voice", label="English voice engine", type="segmented",
         options=[["mac", "macOS"], ["kokoro", "Kokoro"]],
         help="macOS = same kind of voice as Turkish. Kokoro = a British voice that runs offline."),
    dict(key="EN_MAC_VOICE", section="Voice", label="English voice (macOS)", type="voice", lang="en",
         show_if={"EN_ENGINE": "mac"}),
    dict(key="EN_VOICE", section="Voice", label="English voice (Kokoro)", type="select",
         options=[[v, v] for v in KOKORO_VOICES], show_if={"EN_ENGINE": "kokoro"}),
    dict(key="EN_MAC_RATE", section="Voice", label="English speed", type="range", min=120, max=280, step=5,
         unit="words/min", show_if={"EN_ENGINE": "mac"}),
    # AI
    dict(key="CLAUDE_MODEL", section="AI brain", label="Claude model", type="select", options=MODELS,
         help="Haiku answers fastest. Sonnet/Opus are better at complex tasks but slower and use more of your plan."),
    dict(key="CLAUDE_MAX_TURNS", section="AI brain", label="Max tool steps per request", type="number",
         min=1, max=100),
    dict(key="USE_LOCAL_FALLBACK", section="AI brain", label="Offline fallback (Ollama)", type="bool",
         help="If Claude is unreachable, answer with the local model."),
    dict(key="OLLAMA_MODEL", section="AI brain", label="Offline model", type="text",
         show_if={"USE_LOCAL_FALLBACK": True}, help="e.g. qwen3:8b or qwen3:4b (must be pulled with ollama)."),
    # Listening
    dict(key="WAKE_ON_NAME", section="Listening", label="Wake on a plain “Jarvis”", type="bool",
         help="Besides “Hey Jarvis”. Also lets you say “Jarvis, saat kaç?” in one breath."),
    dict(key="WAKE_THRESHOLD", section="Listening", label="“Hey Jarvis” sensitivity", type="range",
         min=0.3, max=0.9, step=0.05, help="Higher = fewer false wake-ups, but you may need to repeat."),
    dict(key="SILENCE_SEC", section="Listening", label="Pause that ends your sentence", type="range",
         min=0.4, max=2.0, step=0.1, unit="s"),
    dict(key="FOLLOW_UP_SEC", section="Listening", label="Keep listening after a reply", type="range",
         min=0, max=10, step=0.5, unit="s", help="Time for a follow-up question without saying Jarvis."),
    dict(key="MAX_RECORD_SEC", section="Listening", label="Longest command", type="range",
         min=5, max=60, step=5, unit="s"),
    dict(key="BARGE_IN", section="Listening", label="Interrupt Jarvis while it talks", type="bool"),
    dict(key="BARGE_SPEECH_SEC", section="Listening", label="Talk this long to interrupt", type="range",
         min=0.3, max=60, step=0.1, unit="s", show_if={"BARGE_IN": True},
         help="60 = only saying “Jarvis” interrupts (Jarvis's own voice can trigger short values)."),
    # Orb
    dict(key="SHOW_ORB", section="Orb", label="Show the animated orb", type="bool"),
    dict(key="ORB_CORNER", section="Orb", label="Position", type="select", show_if={"SHOW_ORB": True},
         options=[["bottom-right", "Bottom right"], ["bottom-left", "Bottom left"],
                  ["top-right", "Top right"], ["top-left", "Top left"]]),
    dict(key="ORB_SIZE", section="Orb", label="Size", type="range", min=90, max=260, step=10, unit="px",
         show_if={"SHOW_ORB": True}),
    # Advanced
    dict(key="DEBUG_WAKE", section="Advanced", label="Print wake-word debug info to the log", type="bool"),
]
KEYS = {f["key"] for f in SCHEMA}


# -- load / save -----------------------------------------------------------------
def load_overrides() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in KEYS}
    except (FileNotFoundError, ValueError):
        return {}


def current_values() -> dict:
    return {k: getattr(config, k, None) for k in KEYS}


def _coerce(field: dict, value):
    t = field["type"]
    if t == "bool":
        return bool(value)
    if t in ("number", "range"):
        v = float(value)
        v = max(field.get("min", v), min(field.get("max", v), v))
        return int(v) if float(v).is_integer() and field.get("step", 1) >= 1 else round(v, 3)
    return "" if value is None else str(value)


def save(values: dict) -> dict:
    """Validate and write settings.json. Returns the saved values."""
    out = load_overrides()
    for f in SCHEMA:
        if f["key"] in values:
            out[f["key"]] = _coerce(f, values[f["key"]])
    SETTINGS_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def mac_voices() -> list[dict]:
    """Installed macOS voices (Siri voices aren't listed; they're reachable as the 'system' voice)."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\b", line)
        if m:
            voices.append({"name": m.group(1).strip(), "locale": m.group(2)})
    return voices


# -- the window's API (called from JavaScript) ----------------------------------------
class SettingsApi:
    def __init__(self, on_restart=None):
        self._on_restart = on_restart

    def get_schema(self):
        return SCHEMA

    def get_values(self):
        return current_values() | load_overrides()

    def get_voices(self):
        return mac_voices()

    def save(self, values):
        save(values)
        return True

    def preview(self, lang, engine, voice, rate):
        text = ("Merhaba efendim, ben Jarvis. Size nasıl yardımcı olabilirim?" if lang == "tr"
                else "Good evening, sir. I am Jarvis. How may I help you?")
        if engine == "kokoro":
            return "Kokoro preview works after saving and restarting Jarvis."
        cmd = ["say", "-r", str(int(float(rate))), text]
        if voice and voice != "system":
            cmd[1:1] = ["-v", voice]
        subprocess.Popen(cmd)
        return ""

    def save_and_restart(self, values):
        save(values)
        threading.Timer(0.3, self._restart).start()
        return True

    def _restart(self):
        if self._on_restart:
            self._on_restart()
        else:
            restart_jarvis()


def restart_jarvis() -> None:
    """Restart the running Jarvis (used when this window runs on its own)."""
    script = config.BASE_DIR / "Restart Jarvis.command"
    subprocess.Popen(["/bin/zsh", str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


_window = None


def open_window(on_restart=None):
    """Open the settings window (or bring it to the front). Safe to call from any thread."""
    import webview
    global _window
    if _window is not None:
        try:
            _window.show()
            _activate()
            return _window
        except Exception:
            _window = None
    _window = webview.create_window(
        "Jarvis Settings", url=HTML.as_uri(), js_api=SettingsApi(on_restart),
        width=800, height=600, min_size=(700, 460), background_color="#f5f5f7",
    )

    def closed():
        global _window
        _window = None
    _window.events.closed += closed
    _window.events.loaded += _activate
    return _window


def _activate():
    """Bring Jarvis's windows to the front (Jarvis has no Dock icon, so macOS won't do it by itself)."""
    try:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper
        AppHelper.callAfter(lambda: NSApplication.sharedApplication().activateIgnoringOtherApps_(True))
    except Exception:
        pass


if __name__ == "__main__":
    import webview
    open_window()
    webview.start()
    sys.exit(0)
