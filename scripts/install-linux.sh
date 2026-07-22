#!/usr/bin/env bash
set -euo pipefail

# install-linux.sh — set up Aparté in a local virtualenv.
#
# Steps: (optionally) apt-install system deps, create .venv (with an ensurepip
# fallback for minimal Python builds), install Aparté with the whisper +
# recording extras (plus cuda when an NVIDIA GPU is detected), write a default
# config, and register the desktop launcher (icon + menu entry).
#
# Usage:
#   ./scripts/install-linux.sh                    # venv install + desktop launcher
#   ./scripts/install-linux.sh --with-system-deps # also apt-install audio/clipboard/paste tools (needs sudo)
#
# Re-running is safe: an existing .venv is reused and config init is a no-op.

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
    sudo apt install -y alsa-utils ffmpeg wl-clipboard wtype xclip xdotool \
      python3-gi gir1.2-ayatanaappindicator3-0.1
  else
    echo "apt not found; install recording/clipboard packages with your package manager." >&2
  fi
fi

# Create the virtualenv. Some minimal Python builds ship without ensurepip,
# which makes `python -m venv` produce a venv with no pip. Detect that and
# bootstrap pip from the system interpreter.
#
# --system-site-packages is what lets the venv see PyGObject, which is a system
# package and not installable from pip. Without it there is no tray icon. Aparté
# still installs its own dependencies into the venv, where they take precedence.
if [[ ! -x ".venv/bin/python" ]]; then
  if "$PYTHON" -m venv --system-site-packages .venv 2>/dev/null && [[ -x ".venv/bin/pip" ]]; then
    :
  else
    echo "Bootstrapping pip into the virtualenv (ensurepip unavailable)..."
    rm -rf .venv
    "$PYTHON" -m venv --system-site-packages --without-pip .venv
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
python -m aparte config init || true
python -m aparte install-desktop --force

echo
echo "Installed Aparté."
echo "Run: source .venv/bin/activate && aparte doctor"
echo "Bind the dictation hotkey (Cinnamon/GNOME): aparte install-hotkey"
echo "If you skipped --with-system-deps, install the copy/paste tools for your session:"
echo "  X11:     sudo apt install xclip xdotool"
echo "  Wayland: sudo apt install wl-clipboard wtype"
