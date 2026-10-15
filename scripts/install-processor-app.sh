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

# Icon: a simple d20-green tile drawn with Pillow, converted to .icns.
TMP="$(mktemp -d)"
"$UV" run --project "$REPO" python - "$TMP" <<'PY'
import sys
from PIL import Image, ImageDraw, ImageFont
out = sys.argv[1]
img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((64, 64, 960, 960), radius=200, fill=(44, 94, 63))
d.polygon([(512, 210), (790, 370), (790, 680), (512, 840), (234, 680), (234, 370)], outline=(240, 230, 200), width=36)
try:
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 230)
except OSError:
    font = ImageFont.load_default()
d.text((512, 525), "20", fill=(240, 230, 200), font=font, anchor="mm")
iconset = f"{out}/icon.iconset"
import os
os.makedirs(iconset)
for size in (16, 32, 128, 256, 512):
    img.resize((size, size), Image.LANCZOS).save(f"{iconset}/icon_{size}x{size}.png")
    img.resize((size * 2, size * 2), Image.LANCZOS).save(f"{iconset}/icon_{size}x{size}@2x.png")
PY
iconutil -c icns "$TMP/icon.iconset" -o "$APP/Contents/Resources/icon.icns"
rm -rf "$TMP"
touch "$APP"
echo "Installed: $APP"
