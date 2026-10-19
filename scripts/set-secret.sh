#!/usr/bin/env bash
# Set a secret in Railway (askdnd-v2) and in local .env without it ever
# appearing on screen, in shell history, or in a chat.
#
#   scripts/set-secret.sh ANTHROPIC_API_KEY            # prompts (hidden input)
#   scripts/set-secret.sh ANTHROPIC_API_KEY --clipboard  # reads from clipboard
#   scripts/set-secret.sh ANTHROPIC_API_KEY --local-only
#   scripts/set-secret.sh AWS_SECRET_ACCESS_KEY --service askdnd-backup   # another Railway service
set -euo pipefail

name="${1:?usage: scripts/set-secret.sh NAME [--clipboard] [--local-only]}"
shift
from_clipboard=false
local_only=false
service=askdnd-v2
while [ $# -gt 0 ]; do
  case "$1" in
    --clipboard) from_clipboard=true ;;
    --local-only) local_only=true ;;
    --service) shift; service="${1:?--service needs a name}" ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
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
  if ! out="$(printf '%s' "$value" | railway variable set "$name" --stdin --service "$service" --environment production --skip-deploys 2>&1)"; then
    echo "✗ Railway update failed:" >&2
    echo "$out" >&2
    exit 1
  fi
  echo "✓ $name saved to Railway ($service, production) — takes effect on next deploy"
fi
