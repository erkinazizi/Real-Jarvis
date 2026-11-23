"""Offline fallback brain: Qwen3 on Ollama. Chat only, no tools."""
import requests

import config
import persona

PERSONA = (
    "You are JARVIS, {user}'s AI assistant. You are in offline mode, so you cannot act on the "
    "computer; just answer. Reply in {language} only, in 1 to 3 short spoken sentences, no markdown.\n"
    "{personality}"
)

_history: list[dict] = []


def ask_local(text: str, lang: str) -> str:
    language = "Turkish" if lang == "tr" else "English"
    _history.append({"role": "user", "content": text})
    del _history[:-12]                                   # keep the last few turns
    r = requests.post(
        config.OLLAMA_URL,
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "system", "content": PERSONA.format(language=language, user=config.USER_NAME,
                                personality=persona.personality_prompt(config.TONE, config.HUMOR, config.USER_NAME))}, *_history],
            "stream": False,
            "think": False,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
        },
        timeout=120,
    )
    r.raise_for_status()
    answer = r.json()["message"]["content"].strip()
    _history.append({"role": "assistant", "content": answer})
    return answer
