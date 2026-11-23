#!/bin/zsh
# Builds Jarvis.app (in /Applications, or ~/Applications if that isn't writable).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="/Applications"
[[ -w "$DEST" ]] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
APP="$DEST/Jarvis.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$DIR/assets/Jarvis.icns" "$APP/Contents/Resources/Jarvis.icns"

cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleDisplayName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>app.jarvis.assistant</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>CFBundleIconFile</key><string>Jarvis</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Jarvis listens for "Hey Jarvis" and your voice commands.</string>
  <key>NSAppleEventsUsageDescription</key><string>Jarvis controls apps on your Mac when you ask it to.</string>
</dict></plist>
PL

cat > "$APP/Contents/MacOS/Jarvis" <<SH
#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
cd "$DIR"
mkdir -p logs
# already running? wake it up (same as saying "Jarvis") instead of starting a second one
pgrep -f "$DIR/main.py" >/dev/null && { touch "$DIR/logs/.wake"; exit 0; }
exec "$DIR/.venv/bin/python" -u "$DIR/main.py" >> "$DIR/logs/app.log" 2>&1
SH
chmod +x "$APP/Contents/MacOS/Jarvis"

touch "$APP"                                   # refresh the icon cache
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true
echo "✅ Built $APP  — open it from Launchpad / Spotlight ('Jarvis')."
