#!/usr/bin/env bash
# Builds "askdnd Processor.app" in ~/Applications. Double-clicking it starts
# Ollama (if needed) and the local processor, then opens it in the browser.
#   scripts/install-processor-app.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/askdnd Processor.app"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>askdnd Processor</string>
  <key>CFBundleDisplayName</key><string>askdnd Processor</string>
  <key>CFBundleIdentifier</key><string>ai.askdnd.processor</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>askdnd-processor</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/askdnd-processor" <<LAUNCH
#!/bin/bash
# GUI apps don't load your shell profile, so paths are absolute.
PORT=8765
LOG="\$HOME/Library/Logs/askdnd-processor.log"
up() { /usr/bin/curl -s -o /dev/null "http://127.0.0.1:\$PORT/"; }
if ! up; then
  if ! /usr/bin/curl -s -o /dev/null http://127.0.0.1:11434/api/tags; then
    /usr/bin/open -a Ollama || true
  fi
  cd "$REPO" && nohup "$UV" run python -m transcript_filter.web >>"\$LOG" 2>&1 &
  for i in \$(seq 1 60); do up && break; sleep 0.5; done
fi
/usr/bin/open "http://127.0.0.1:\$PORT/"
LAUNCH
chmod +x "$APP/Contents/MacOS/askdnd-processor"

# Icon: the askdnd d20 (app/static/icons), converted to .icns.
TMP="$(mktemp -d)"
mkdir "$TMP/icon.iconset"
SRC="$REPO/app/static/icons/android-chrome-512x512.png"
for size in 16 32 128 256 512; do
  sips -z $size $size "$SRC" --out "$TMP/icon.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2)); [ $double -gt 512 ] && double=512
  sips -z $double $double "$SRC" --out "$TMP/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/icon.iconset" -o "$APP/Contents/Resources/icon.icns"
rm -rf "$TMP"
touch "$APP"
echo "Installed: $APP"
