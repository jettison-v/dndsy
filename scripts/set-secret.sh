#!/usr/bin/env bash
# Set a secret in Railway (askdnd-v2) and in local .env without it ever
# appearing on screen, in shell history, or in a chat.
#
#   scripts/set-secret.sh ANTHROPIC_API_KEY            # prompts (hidden input)
#   scripts/set-secret.sh ANTHROPIC_API_KEY --clipboard  # reads from clipboard
#   scripts/set-secret.sh ANTHROPIC_API_KEY --local-only
set -euo pipefail

name="${1:?usage: scripts/set-secret.sh NAME [--clipboard] [--local-only]}"
shift
from_clipboard=false
local_only=false
for arg in "$@"; do
  case "$arg" in
    --clipboard) from_clipboard=true ;;
    --local-only) local_only=true ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

if $from_clipboard; then
  value="$(pbpaste)"
elif [ -t 0 ]; then
  read -r -s -p "Paste value for $name (hidden), then Enter: " value
  echo
else
  read -r value
fi
value="$(printf '%s' "$value" | tr -d '\r\n')"
[ -n "$value" ] || { echo "No value given; nothing changed." >&2; exit 1; }

cd "$(dirname "$0")/.."

# Local .env: replace the line if present, otherwise append.
touch .env
grep -v "^${name}=" .env > .env.tmp || true
printf '%s=%s\n' "$name" "$value" >> .env.tmp
mv .env.tmp .env
chmod 600 .env
echo "✓ $name saved to local .env"

if ! $local_only; then
  if ! out="$(printf '%s' "$value" | railway variable set "$name" --stdin --service askdnd-v2 --environment production --skip-deploys 2>&1)"; then
    echo "✗ Railway update failed:" >&2
    echo "$out" >&2
    exit 1
  fi
  echo "✓ $name saved to Railway (askdnd-v2, production) — takes effect on next deploy"
fi
