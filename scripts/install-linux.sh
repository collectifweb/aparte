#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"

# Optional system packages for recording, transcription decoding, and
# clipboard/paste integration. Run with --with-system-deps to install them
# via apt (requires sudo). Skipped by default so the script stays non-root.
if [[ "${1:-}" == "--with-system-deps" ]]; then
  if command -v apt >/dev/null 2>&1; then
    echo "Installing system packages (sudo)..."
    sudo apt update
    sudo apt install -y alsa-utils ffmpeg wl-clipboard wtype xclip xdotool
  else
    echo "apt not found; install recording/clipboard packages with your package manager." >&2
  fi
fi

# Create the virtualenv. Some minimal Python builds ship without ensurepip,
# which makes `python -m venv` produce a venv with no pip. Detect that and
# bootstrap pip from the system interpreter.
if [[ ! -x ".venv/bin/python" ]]; then
  if "$PYTHON" -m venv .venv 2>/dev/null && [[ -x ".venv/bin/pip" ]]; then
    :
  else
    echo "Bootstrapping pip into the virtualenv (ensurepip unavailable)..."
    rm -rf .venv
    "$PYTHON" -m venv --without-pip .venv
    "$PYTHON" -m pip --python .venv/bin/python install --upgrade pip setuptools wheel
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip

# Install GPU runtime libs when an NVIDIA GPU is present so faster-whisper can
# use CUDA. The app preloads these pip-provided libs automatically and falls
# back to CPU if CUDA is unusable, so this is safe to install opportunistically.
EXTRAS="whisper,recording"
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA GPU detected; including CUDA runtime libraries."
  EXTRAS="$EXTRAS,cuda"
fi
python -m pip install -e ".[$EXTRAS]"
python -m whispr_flow_linux config init || true
python -m whispr_flow_linux install-desktop --force

echo
echo "Installed Whispr Flow Linux."
echo "Run: source .venv/bin/activate && whispr-flow doctor"
echo "For CLI copy/paste on X11, install: sudo apt install xclip xdotool"
echo "On Wayland, install: sudo apt install wl-clipboard wtype"
