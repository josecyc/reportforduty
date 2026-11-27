#!/bin/sh
# Rebuild the public site and push it to the gh-pages branch, which GitHub Pages serves at
# https://reportforduty.si. Run from anywhere; commit and push main first.
#
#     tools/publish.sh ["extra commit message lines"]
set -eu
cd "$(dirname "$0")/.."
DOMAIN=reportforduty.si
ref=$(git rev-parse --short HEAD)
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "main has uncommitted changes; commit them first so the site matches a commit" >&2
  exit 1
fi
tmp=$(mktemp -d "${TMPDIR:-/tmp}/rfd-pages.XXXXXX")
cleanup() { git worktree remove --force "$tmp" 2>/dev/null || true; }
trap cleanup EXIT
git fetch -q origin gh-pages
git worktree add -q --detach "$tmp" origin/gh-pages
nice -n 19 python3 tools/build_static.py --out "$tmp" --domain "$DOMAIN"
cd "$tmp"
git add -A
if git diff --cached --quiet; then
  echo "the public site already matches main $ref"
  exit 0
fi
git commit -q -m "Publish main $ref" ${1:+-m "$1"}
git push -q origin HEAD:gh-pages
echo "published main $ref to gh-pages; GitHub Pages updates https://$DOMAIN within a minute or two"
