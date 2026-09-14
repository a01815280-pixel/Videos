#!/bin/zsh
set -e
cd "$(dirname "$0")"

echo "== Flashing-Light Video Dataset Tool setup =="

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is not installed. Install it from https://brew.sh/ and run this setup again."
    exit 1
fi

brew install python@3.12 ffmpeg node
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Could not find Homebrew Python 3.12 at $PYTHON_BIN"
    exit 1
fi

if [ -d ".venv" ]; then
    VENV_PY=".venv/bin/python"
    if [ ! -x "$VENV_PY" ] || ! "$VENV_PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)' >/dev/null 2>&1; then
        echo "Existing .venv is not Python 3.12. Recreating it..."
        rm -rf .venv
    fi
fi

if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p data/inbox data/auto_review data/raw/flashing data/raw/no_flashing data/clips lstm

python - <<'PY'
import platform
import sys

print("Python:", sys.version.split()[0])
print("Architecture:", platform.machine())

import PySide6
import cv2
import numpy
import yt_dlp
import iris_pse_detection

print("PySide6: OK")
print("OpenCV: OK")
print("NumPy: OK")
print("yt-dlp: OK")
print("IRIS-PSE-Detection: OK")
PY

chmod +x run_app.command setup_mac.command
printf '\nSetup complete. Start the app with: ./run_app.command\n'
