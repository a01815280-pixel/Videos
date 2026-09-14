#!/bin/zsh
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "The project is not set up yet. Run ./setup_mac.command first."
  read -n 1
  exit 1
fi
source .venv/bin/activate
exec python src/app.py
