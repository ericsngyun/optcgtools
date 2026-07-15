#!/usr/bin/env bash
set -euo pipefail

REPO="ericsngyun/optcg-cards-css"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required: https://cli.github.com/" >&2
  exit 1
fi

gh auth status
gh repo create "$REPO" \
  --public \
  --description "Svelte/CSS material lab for physically plausible One Piece Card Game holofoil effects" \
  --source=. \
  --remote=origin \
  --push

echo "Published https://github.com/$REPO"
