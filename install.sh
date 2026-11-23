#!/bin/zsh
# One-time install for Jarvis on macOS (Apple Silicon).
set -e
cd "$(dirname "$0")"

command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { echo "Jarvis needs an Apple-Silicon Mac (M1 or newer)."; exit 1; }
brew install python@3.12 espeak-ng ollama

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python setup_models.py

echo "\n▶ Offline brain (Qwen3 8B, ~5 GB)"
brew services start ollama
sleep 3
ollama pull qwen3:8b || echo "⚠️  ollama pull failed - run 'ollama pull qwen3:8b' later"

echo "\n▶ Building Jarvis.app"
./make_app.sh

echo "\n✅ Installed. Next steps:"
echo "  1) Log in to Claude once:  ./login.sh   (type /login, finish in the browser, then /exit)"
echo "  2) Test:  source .venv/bin/activate && python tts.py && python audio.py && python test_brain.py"
echo "  3) Run:   open Jarvis from Launchpad/Spotlight  (or ./run.sh to see logs in Terminal)"
echo "  4) Optional: ./autostart.sh on   (start Jarvis at login)"
