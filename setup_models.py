"""One-time download + warm-up of every local model.  Run:  python setup_models.py"""
import shutil

import numpy as np

import config


def step(msg: str) -> None:
    print(f"\n▶ {msg}")


def main() -> None:
    config.MODELS_DIR.mkdir(exist_ok=True)
    config.LOG_DIR.mkdir(exist_ok=True)
    config.SAFE_DIR.mkdir(exist_ok=True)

    step("Wake word model (hey_jarvis)")
    import openwakeword.utils
    try:
        openwakeword.utils.download_models(model_names=["hey_jarvis"])
    except TypeError:                       # older openwakeword
        openwakeword.utils.download_models()

    step("Turkish voice (Piper, tr_TR-dfki-medium)")
    from huggingface_hub import hf_hub_download
    base = "tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx"
    for name in (base, base + ".json"):
        src = hf_hub_download("rhasspy/piper-voices", name)
        shutil.copy(src, config.MODELS_DIR / name.split("/")[-1])

    step(f"Whisper ({config.WHISPER_MODEL}) - ~1.6 GB on first run")
    import mlx_whisper
    mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32),
                           path_or_hf_repo=config.WHISPER_MODEL, language="en")

    step("Kokoro English voice")
    from kokoro import KPipeline
    for _ in KPipeline(lang_code="b", repo_id="hexgrad/Kokoro-82M")("Ready.", voice=config.EN_VOICE):
        pass

    step("Silero VAD")
    from silero_vad import load_silero_vad
    load_silero_vad()

    print("\n✅ All models ready. Next: python tts.py  (voice test)")


if __name__ == "__main__":
    main()
