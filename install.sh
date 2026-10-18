#!/usr/bin/env bash
# Tallowmark installer -- project-level dependencies only, then exits.
# No sudo, no system packages, no service management. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "install: Tallowmark needs Python 3.9 or newer (found: $("$PYTHON" -V 2>&1))" >&2
    exit 1
fi

# 1. Fresh packaging tooling: old pip silently fails modern editable installs.
"$PYTHON" -m pip install --upgrade pip setuptools wheel

# 2. Declared dependencies (pytest -- the tool itself is standard library only).
"$PYTHON" -m pip install -r requirements.txt

# 3. Install the console script `tallowmark` into the current environment.
"$PYTHON" -m pip install -e .

# 4. Cheap self-check so an incomplete environment fails here, not at first use.
"$PYTHON" -c 'import tallowmark; assert callable(tallowmark.main); assert tallowmark.__version__'

echo
echo "Tallowmark installed."
echo "  run:   tallowmark --help          (or: $PYTHON tallowmark.py --help)"
echo "  demo:  bash demo.sh"
echo "  tests: $PYTHON -m pytest"
