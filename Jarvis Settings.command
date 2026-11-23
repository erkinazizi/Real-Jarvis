#!/bin/zsh
# Double-click to open Jarvis's settings (works even when Jarvis isn't running).
cd "$(dirname "$0")"
exec .venv/bin/python settings.py
