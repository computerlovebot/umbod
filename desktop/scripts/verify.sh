#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd python && uv run --locked ruff check . && uv run --locked pytest -q)
bash scripts/build.sh dev
swift run --package-path native UmbodTests
python3 scripts/native-smoke.py "dist/Umbod Dev.app"
