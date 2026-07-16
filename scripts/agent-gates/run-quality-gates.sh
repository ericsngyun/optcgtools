#!/usr/bin/env bash
# Complete quality-gate sequence. Agents must run this before reporting
# completion of any integration-ready change.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== git diff --check =="
git diff --check
git diff --cached --check

echo "== agent gates (staged) =="
python3 scripts/agent-gates/check-private-media.py --staged
python3 scripts/agent-gates/check-approved-assets.py --staged
python3 scripts/agent-gates/check-generated-artifacts.py --staged

echo "== upstream source pin =="
npm run check:source-pin

echo "== web build =="
npm run build

echo "== web tests =="
npm run test:web

echo "== python lint =="
uv run ruff check src tests

echo "== python tests =="
uv run pytest

echo "All quality gates passed."
