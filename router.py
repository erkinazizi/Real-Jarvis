"""Instant commands that never reach the LLM (sub-second)."""
import datetime as dt
import re
import subprocess

EXIT = object()
SETTINGS = object()

TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _osa(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


FILLERS = re.compile(
    r"^(?:(?:ok(?:ay)?|good|great|alright|well|so|now|please|hey|jarvis|tamam|peki|şimdi|lütfen)[\s,.!]+)+",
    re.I,
)


def _norm(text: str) -> str:
    """Drop trailing punctuation and leading fillers: 'Okay, good. Open Safari.' -> 'Open Safari'."""
    t = re.sub(r"[.!?,]+$", "", text.strip()).strip()
    return FILLERS.sub("", t).strip()


def handle(text: str, lang: str):
    """Return a reply string, EXIT, SETTINGS, or None (= let the brain handle it)."""
    t = _norm(text)
    low = t.lower()

    # settings window
    if re.fullmatch(r"(open |show )?(your |the )?settings( menu| window)?|"
                    r"ayarlar(ı|i)?( menüsünü| penceresini)?( aç| göster)?|ayarları aç", low):
        return SETTINGS
    tr = lang == "tr"

    # goodbye
    if re.fullmatch(r"(goodbye|bye|good night|shut down|go to sleep)(,? \w+)?|"
                    r"görüşürüz(,? \w+)?|hoşça kal(,? \w+)?|kapan(,? \w+)?|iyi geceler(,? \w+)?", low):
        return EXIT

    # volume
    if re.search(r"\b(volume up|louder)\b|sesi aç|sesi yükselt", low):
        _osa("set volume output volume ((output volume of (get volume settings)) + 15)")
        return "Hemen efendim." if tr else "Louder, sir."
    if re.search(r"\b(volume down|quieter)\b|sesi kıs|sesi azalt", low):
        _osa("set volume output volume ((output volume of (get volume settings)) - 15)")
        return "Kıstım efendim." if tr else "Turning it down, sir."
    if re.search(r"^(mute|unmute)\b|sesi kapat", low):
        _osa("set volume output muted (not (output muted of (get volume settings)))")
        return "Tamam efendim." if tr else "Done, sir."

    # time / date
    if re.search(r"what time is it|what'?s the time|what is the time|saat kaç", low):
        now = dt.datetime.now()
        return f"Saat {now:%H:%M} efendim." if tr else f"It's {now:%-I:%M %p}, sir."
    if re.search(r"what day is it|what's the date|bugün günlerden ne|bugün ayın kaçı", low):
        now = dt.datetime.now()
        return (f"Bugün {TR_DAYS[now.weekday()]}, {now:%d.%m.%Y} efendim." if tr
                else f"It's {now:%A, %B %-d}, sir.")

    # open an app:  "open Spotify"  /  "Spotify'ı aç", "Safari aç"
    m = re.match(r"^(?:jarvis,?\s+)?open\s+(.+)$", t, re.I) or \
        re.match(r"^(.+?)(?:['’][a-zıiuüşğçö]+)?\s+aç$", t, re.I)
    if m:
        app = m.group(1).strip()
        ok = subprocess.run(["open", "-a", app], capture_output=True).returncode == 0
        if ok:
            return f"{app} açılıyor efendim." if tr else f"Opening {app}, sir."
        return None          # not an app name -> let Claude figure it out

    return None
