#!/usr/bin/env bash
set -euo pipefail

SAM2_COMMIT="2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_REPOSITORY="https://github.com/facebookresearch/sam2.git"
VENDOR_ROOT="${SAM2_VENDOR_ROOT:-.vendor}"
SAM2_ROOT="${VENDOR_ROOT}/sam2"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

mkdir -p "${VENDOR_ROOT}"
if [[ ! -d "${SAM2_ROOT}/.git" ]]; then
  git clone --filter=blob:none "${SAM2_REPOSITORY}" "${SAM2_ROOT}"
fi

git -C "${SAM2_ROOT}" fetch --depth=1 origin "${SAM2_COMMIT}"
git -C "${SAM2_ROOT}" checkout --detach "${SAM2_COMMIT}"
ACTUAL_COMMIT="$(git -C "${SAM2_ROOT}" rev-parse HEAD)"
if [[ "${ACTUAL_COMMIT}" != "${SAM2_COMMIT}" ]]; then
  echo "SAM 2 checkout mismatch: ${ACTUAL_COMMIT}" >&2
  exit 1
fi

cat <<'EOF'
SAM 2 requires a platform-appropriate PyTorch and TorchVision installation.
Install the official build for your CUDA/ROCm/MPS environment first, then rerun
this script with SAM2_SKIP_TORCH_CHECK=1. See: https://pytorch.org/get-started/locally/
EOF

if [[ "${SAM2_SKIP_TORCH_CHECK:-0}" != "1" ]]; then
  uv run python - <<'PY'
import sys
try:
    import torch
    import torchvision
except ImportError:
    sys.exit("PyTorch and TorchVision must be installed before SAM 2")
print(f"torch={torch.__version__} torchvision={torchvision.__version__}")
PY
fi

uv pip install --python .venv/bin/python -e "${SAM2_ROOT}"

uv run python - <<PY
from pathlib import Path
import subprocess
import sam2
root = Path(next(iter(sam2.__path__))).resolve().parent
commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
assert commit == "${SAM2_COMMIT}", (commit, "${SAM2_COMMIT}")
print(f"SAM 2.1 installed at pinned commit {commit}")
PY
