#!/bin/zsh
# Start Jarvis automatically when you log in.   ./autostart.sh on  |  ./autostart.sh off
APP="/Applications/Jarvis.app"; [[ -d "$APP" ]] || APP="$HOME/Applications/Jarvis.app"
[[ -d "$APP" ]] || { echo "Build the app first: ./make_app.sh"; exit 1; }

# remove the old LaunchAgent from version 1, if any
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.erkin.jarvis.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.erkin.jarvis.plist"

osascript -e 'tell application "System Events" to delete (every login item whose name is "Jarvis")' >/dev/null 2>&1 || true
if [[ "$1" == "off" ]]; then echo "Autostart off."; exit 0; fi
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP\", hidden:true}" >/dev/null
echo "Autostart on: Jarvis starts when you log in."
