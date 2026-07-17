#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$ROOT/upstream/pokemon-cards-css"
REPO="https://github.com/simeydotme/pokemon-cards-css.git"
PIN="acb1197633e749a1fba4412231db2f6581586d00"

if [ -d "$TARGET/.git" ]; then
  git -C "$TARGET" fetch --depth 1 origin "$PIN"
else
  rm -rf "$TARGET"
  git clone --no-checkout --filter=blob:none "$REPO" "$TARGET"
fi

git -C "$TARGET" fetch --depth 1 origin "$PIN"
git -C "$TARGET" checkout --detach "$PIN"

echo "Pinned upstream source at $PIN"
