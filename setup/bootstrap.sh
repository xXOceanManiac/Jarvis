#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel setuptools
pip install -r requirements.txt

echo "V5.1 bootstrap complete."
echo "Next: copy .env.example to .env and fill in secrets."
