"""Jarvis configuration. Tuned for MacBook M4 / 16 GB."""
import logging
import os
import pwd
import warnings
from pathlib import Path

# quiet the harmless library warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("torch.distributed.elastic").setLevel(logging.ERROR)

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"

# --- Language -------------------------------------------------------------
LANGUAGE = "tr"               # default / fallback language: "tr" or "en"

# --- Personality ------------------------------------------------------------
TONE = "formal"               # "formal" | "polite" | "friendly" | "casual"
HUMOR = "witty"               # "none" | "light" | "witty"

# --- Audio -------------------------------------------------------------
SAMPLE_RATE = 16000
WAKE_THRESHOLD = 0.5          # raise to 0.6-0.7 if it wakes up by mistake
SILENCE_SEC = 0.7             # how long a pause ends your sentence
IGNORE_START_SEC = 0.25       # ignore the first moment after the wake word / chime
MIN_SPEECH_CHUNKS = 3         # ~100 ms of speech needed before recording "starts"
MAX_RECORD_SEC = 20
FOLLOW_UP_SEC = 4.0           # after a reply, listen this long without the wake word

# wake on a plain "Jarvis" too (checked with Whisper), e.g. "Jarvis, saat kaç?" in one breath
WAKE_ON_NAME = True
NAME_MAX_SEC = 3.0            # phrases longer than this (+1 s) aren't checked for the name
DEBUG_WAKE = False            # print wake-word scores / what Whisper heard

# barge-in: talk over Jarvis to interrupt it
BARGE_IN = True
BARGE_SPEECH_SEC = 60         # talking over Jarvis doesn't stop it (its own voice kept triggering this);
                              # saying "Jarvis" does. Lower (e.g. 0.5) to stop on any speech again
BARGE_MIN_RMS = 0.02          # ignore quieter sounds
BARGE_ECHO_FACTOR = 2.0       # your voice must be this much louder than Jarvis's own echo

# --- Speech to text (local, Apple Silicon / MLX) ------------------------
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

# --- Text to speech (local) ---------------------------------------------
EN_ENGINE = "mac"             # "mac" = same macOS system voice as Turkish, "kokoro" = British Kokoro voice
EN_MAC_VOICE = "system"       # "system" = System Settings > Spoken Content voice, or a name like "Daniel"
EN_MAC_RATE = 190             # words per minute
EN_VOICE = "bm_george"        # Kokoro British male; try "bm_lewis" / "bm_fable"
WAKE_REPLIES = {
    "tr": ["Buyurun efendim?", "Efendim?", "Dinliyorum efendim."],
    "en": ["Yes, sir?", "At your service, sir.", "Sir?", "I'm listening, sir."],
}
TR_ENGINE = "mac"             # "mac" = macOS Turkish voice (Yelda), "piper" = old Piper voice
TR_MAC_VOICE = "system"       # "system" = System Settings > Spoken Content voice (e.g. Siri Voice 2)
                              # None = best installed Turkish voice, or a name like "Yelda (Premium)"
TR_MAC_RATE = 190             # words per minute
TR_PIPER_MODEL = MODELS_DIR / "tr_TR-dfki-medium.onnx"

# --- Brain ---------------------------------------------------------------
WORKDIR = Path.home()                         # where Jarvis runs commands
SAFE_DIR = Path.home() / "Jarvis-Workspace"   # writes here need no approval
AUTH_MODE = "account"                         # "account" = Claude Pro/Max sign-in, "api_key" = key in Keychain
CLAUDE_MODEL = "haiku"                        # fastest. "sonnet" = smarter but slower, None = default (Opus)
CLAUDE_MAX_TURNS = 25                         # max tool steps per request

# Offline fallback (local, via Ollama) when Claude is unreachable
USE_LOCAL_FALLBACK = True
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_KEEP_ALIVE = "10m"                     # "-1" keeps it in RAM forever (uses ~5 GB)

# --- Orb (floating animated indicator) ------------------------------------
SHOW_ORB = True
ORB_SIZE = 150                # px
ORB_MARGIN = 24               # px from the screen edges
ORB_CORNER = "bottom-right"   # "bottom-right" | "bottom-left" | "top-right" | "top-left"

# --- Misc ------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
GREETING = {"tr": "Jarvis hazır. Buyurun efendim.", "en": "Jarvis online. At your service, sir."}
WAKE_FILE = LOG_DIR / ".wake"  # Jarvis.app touches this when opened while Jarvis is already running
# your first name (used in Jarvis's personality); defaults to your macOS account name
USER_NAME = os.environ.get("JARVIS_USER") or (pwd.getpwuid(os.getuid()).pw_gecos or "").split(" ")[0] or "sir"

# --- Your saved settings (from the Settings window) override the defaults above ---
SETTINGS_FILE = BASE_DIR / "settings.json"


def _load_saved_settings() -> None:
    import json
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return
    for key, value in saved.items():
        if key.isupper() and key in globals():
            globals()[key] = value



def _apply_persona() -> None:
    """Greeting and wake-word replies follow the chosen tone (Settings › Personality)."""
    import persona
    global GREETING, WAKE_REPLIES
    GREETING = {lang: persona.phrase("greeting", lang, TONE, USER_NAME) for lang in ("tr", "en")}
    WAKE_REPLIES = {lang: persona.phrase("wake", lang, TONE, USER_NAME) for lang in ("tr", "en")}


_load_saved_settings()
_apply_persona()
