"""Text-only test of the brain (no microphone).  Run:  python test_brain.py"""
import asyncio

from brain import Brain


async def confirm(what: str) -> bool:
    return input(f"\n⚠️  Approve '{what}'? [y/N] ").strip().lower() in ("y", "yes", "e", "evet")


async def speak(text: str) -> None:
    print(f"🤖 {text}")


async def main() -> None:
    brain = Brain(confirm)
    await brain.start()
    print("Type a command (prefix 'tr:' for Turkish). Empty line to quit.")
    try:
        while (line := input("\n🧑 ").strip()):
            lang = "tr" if line.startswith("tr:") else "en"
            await brain.ask(line.removeprefix("tr:").strip(), lang, speak)
    finally:
        await brain.stop()


asyncio.run(main())
