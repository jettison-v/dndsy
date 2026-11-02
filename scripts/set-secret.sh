#!/usr/bin/env bash
# Set a secret in Railway (askdnd-v2) and in local .env without it ever
# appearing on screen, in shell history, or in a chat.
#
#   scripts/set-secret.sh ANTHROPIC_API_KEY            # prompts (hidden input)
#   scripts/set-secret.sh ANTHROPIC_API_KEY --clipboard  # reads from clipboard
#   scripts/set-secret.sh ANTHROPIC_API_KEY --local-only
#   scripts/set-secret.sh SENTRY_DSN --clipboard --railway-only   # beta only: never in local .env
#   scripts/set-secret.sh AWS_SECRET_ACCESS_KEY --service askdnd-backup   # another Railway service
#   scripts/set-secret.sh SENTRY_DSN --mini   # only the Mac Mini's ~/askdnd-tests/.env (the nightly live test), over ssh
set -euo pipefail

name="${1:?usage: scripts/set-secret.sh NAME [--clipboard] [--local-only | --railway-only | --mini] [--service NAME]}"
shift
from_clipboard=false
local_only=false
railway_only=false
mini=false
service=askdnd-v2
while [ $# -gt 0 ]; do
  case "$1" in
    --clipboard) from_clipboard=true ;;
    --local-only) local_only=true ;;
    --railway-only) railway_only=true ;;
    --mini) mini=true ;;
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
  read -r value || true  # (a value piped in without a last newline is still the value)
fi
value="$(printf '%s' "$value" | tr -d '\r\n')"
[ -n "$value" ] || { echo "No value given; nothing changed." >&2; exit 1; }

cd "$(dirname "$0")/.."

if $local_only && $railway_only; then echo "--local-only and --railway-only can't both be set" >&2; exit 1; fi

# The Mac Mini's test folder only (its nightly live test): the value goes over ssh's own input, never on a command line
if $mini; then
  printf '%s=%s\n' "$name" "$value" | ssh mac-mini-server "umask 077; f=\$HOME/askdnd-tests/.env; touch \$f; { grep -v '^${name}=' \$f; cat; } > \$f.tmp; mv \$f.tmp \$f"
  echo "✓ $name saved to the Mac Mini (~/askdnd-tests/.env)"
  exit 0
fi

# Local .env: replace the line if present, otherwise append (not for --railway-only settings, which must stay off locally)
if ! $railway_only; then
  touch .env
  grep -v "^${name}=" .env > .env.tmp || true
  printf '%s=%s\n' "$name" "$value" >> .env.tmp
  mv .env.tmp .env
  chmod 600 .env
  echo "✓ $name saved to local .env"
fi

if ! $local_only; then
  if ! out="$(printf '%s' "$value" | railway variable set "$name" --stdin --service "$service" --environment production --skip-deploys 2>&1)"; then
    echo "✗ Railway update failed:" >&2
    echo "$out" >&2
    exit 1
  fi
  echo "✓ $name saved to Railway ($service, production) — takes effect on next deploy"
fi
