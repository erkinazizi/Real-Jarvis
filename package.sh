#!/bin/zsh
# Makes Jarvis-mac.zip to install Jarvis on another Mac (unzip, then ./install.sh).
set -e
cd "$(dirname "$0")"
OUT="$HOME/Desktop/Jarvis-mac.zip"
rm -f "$OUT"
zip -rq "$OUT" . -x ".venv/*" "models/*" "logs/*" "__pycache__/*" "*/__pycache__/*" ".git/*" "*.DS_Store"
echo "✅ $OUT  ($(du -h "$OUT" | cut -f1)) — copy it to another Apple-Silicon Mac, unzip, run ./install.sh"
