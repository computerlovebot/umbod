#!/bin/bash
set -euo pipefail
# Bundle uv's relocatable CPython plus locked wheels. Build tools are never runtime prerequisites.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$1"
mkdir -p "$DEST"
uv python install 3.14.3
PYTHON="$(uv python find --managed-python 3.14.3)"
PREFIX="$($PYTHON -c 'import sys; print(sys.base_prefix)')"
mkdir -p "$DEST/python"
cp -R "$PREFIX/" "$DEST/python/"
uv export --quiet --project "$ROOT/desktop/python" --frozen --no-dev --no-editable --no-hashes --output-file "$DEST/requirements.txt"
(cd "$ROOT/desktop/python" && uv pip install --python "$DEST/python/bin/python3" --reinstall-package umbod-desktop --reinstall-package umbod-core --reinstall-package umbod --break-system-packages --requirements "$DEST/requirements.txt")
rm "$DEST/requirements.txt"
"$DEST/python/bin/python3" -I -B "$ROOT/desktop/scripts/dependency-notices.py" python "$DEST"
# Compile before signing; runtime must not mutate the signed bundle.
"$DEST/python/bin/python3" -m compileall -q "$DEST/python/lib"
