#!/bin/sh
# Put a branch on staging (staging.askdnd.ai; docs/SETUP_LOG.md › A staging copy), the only way anything goes there.
#
#   scripts/staging.sh jettison-v/some-feature   # try that branch on staging
#   scripts/staging.sh main                      # staging back to what the table runs
#
# Staging is never worked on itself: it's always a copy of a branch that's on GitHub with a pull request open into
# main (or main itself), so everything on it reaches main through that pull request and nothing lives only there.
# It refuses when:
#   - staging has a commit no other branch on GitHub has (replacing it would lose that work),
#   - the branch isn't on GitHub, or has changes not pushed yet,
#   - the branch has no open pull request into main (it could be forgotten).
# It warns when staging's database has migrations the branch doesn't know (staging's data then needs a fresh copy:
# scripts/restore_db.py --into-staging, in the setup log). Then it follows the deploy until staging runs the branch.
set -e
cd "$(dirname "$0")/.."
BRANCH="${1:?usage: scripts/staging.sh <branch>   (or: main)}"

git fetch -q --prune origin
git rev-parse -q --verify "refs/remotes/origin/$BRANCH" >/dev/null || { echo "✗ $BRANCH isn't on GitHub: push it first (git push -u origin $BRANCH)." >&2; exit 1; }
if git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null && [ -n "$(git rev-list "origin/$BRANCH..$BRANCH")" ]; then
  echo "✗ $BRANCH has commits not pushed yet: push them first (git push)." >&2; exit 1
fi

# Nothing on staging may exist only there
others=$(git for-each-ref --format='%(refname)' refs/remotes/origin | grep -v -e '^refs/remotes/origin/staging$' -e '^refs/remotes/origin/HEAD$')
only=$(git rev-list origin/staging --not $others)
if [ -n "$only" ]; then
  echo "✗ Staging has work no other branch has; replacing it would lose it:" >&2
  git log --oneline origin/staging --not $others >&2
  echo "  Put it on a branch first (git push origin origin/staging:refs/heads/<name>), then run this again." >&2
  exit 1
fi

if [ "$BRANCH" != main ] && [ -z "$(gh pr list --head "$BRANCH" --base main --state open --json number --jq '.[].number')" ]; then
  echo "✗ $BRANCH has no open pull request into main: open one first (gh pr create), so it can't be forgotten." >&2; exit 1
fi

ahead=$(git diff --name-only --diff-filter=A "origin/$BRANCH" origin/staging -- migrations/versions)
if [ -n "$ahead" ]; then
  echo "! Staging's database has migrations $BRANCH doesn't know:"; echo "$ahead" | sed 's/^/    /'
  echo "  Staging may not start until its data is a fresh copy (docs/SETUP_LOG.md › A staging copy)."
fi

git push -q -f origin "origin/$BRANCH:refs/heads/staging"
want=$(git rev-parse --short=12 "origin/$BRANCH")
echo "✓ staging is now $BRANCH ($want). Waiting for staging.askdnd.ai to run it…"
for _ in $(seq 60); do
  if curl -s https://staging.askdnd.ai/health | grep -q "\"version\":\"$want"; then echo "✓ staging.askdnd.ai runs $want."; exit 0; fi
  sleep 10
done
echo "! staging.askdnd.ai doesn't run it after 10 minutes: railway logs --service askdnd-staging --environment staging" >&2
exit 1
