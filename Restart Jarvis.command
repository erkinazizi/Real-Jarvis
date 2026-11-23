#!/bin/zsh
# Double-click to (re)start Jarvis.
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/logs/jarvis.pid"
if [[ -f "$PIDFILE" ]] && ps -p "$(cat "$PIDFILE")" -o command= 2>/dev/null | grep -q "main.py"; then
  kill "$(cat "$PIDFILE")" 2>/dev/null; sleep 1
fi
pkill -f "$DIR/main.py" 2>/dev/null
APP="/Applications/Jarvis.app"; [[ -d "$APP" ]] || APP="$HOME/Applications/Jarvis.app"
if [[ -d "$APP" ]]; then
  open "$APP"
else
  cd "$DIR" && mkdir -p logs
  nohup "$DIR/.venv/bin/python" -u "$DIR/main.py" >> "$DIR/logs/app.log" 2>&1 &
fi
echo "Jarvis restarted. You can close this window."
