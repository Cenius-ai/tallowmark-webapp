#!/usr/bin/env bash
# Tallowmark demo -- walks every command end to end against a throwaway store.
# Non-interactive and idempotent: it never touches ~/.tallowmark/store.json.
# Run with:  bash demo.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
DEMO_DIR="$(mktemp -d)"
export TALLOWMARK_FILE="$DEMO_DIR/store.json"
trap 'rm -rf "$DEMO_DIR"' EXIT

show() {
    printf '\n$ tallowmark %s\n' "$*"
}

run() {
    show "$@"
    "$PYTHON" tallowmark.py "$@"
}

run_fail() {
    show "$@"
    status=0
    "$PYTHON" tallowmark.py "$@" || status=$?
    if [ "$status" -eq 0 ]; then
        printf 'demo: expected this command to fail\n' >&2
        exit 1
    fi
    printf '  [exit %d, as expected]\n' "$status"
}

printf 'Tallowmark demo -- throwaway store: %s\n' "$TALLOWMARK_FILE"
printf '=====================================================================\n'

run --version

printf '\n== 1. create wax batches (case-folded slugs, original casing kept)\n'
run batch new Lavender
run batch new Beeswax
run batch new "Cedar & Fig"
run_fail batch new lavender
run_fail batch new "   "
run batch list

printf '\n== 2. count candle dips\n'
run dip add Lavender
run dip add Lavender
run dip add Lavender
run dip add Beeswax
run dip list Lavender

printf '\n== 3. wax batch notes\n'
run note add Lavender poured at 60C, 6 percent fragrance load
run note add Lavender top-up pour at 58C to fill the sink hole
run note add Beeswax single pour, cotton wick, 5 percent load
run note list Lavender
run note list "Cedar & Fig"

printf '\n== 4. cure countdown\n'
run cure set Lavender 48
run cure set Beeswax 72
run cure status Lavender
run cure status "Cedar & Fig"
run_fail cure set Lavender 0
run_fail cure set Lavender abc
run_fail cure set Lavender -5
run_fail cure set Lavender

printf '\n== 5. one batch in detail\n'
run batch show Lavender

printf '\n== 6. status overview\n'
run list

printf '\n== 7. clear a cure and re-check\n'
run cure clear Beeswax
run cure status Beeswax
run list

printf '\n== 8. errors are one line on stderr, exit 1\n'
run_fail dip add Ghost
run_fail note list Ghost

printf '\n== 9. final overview\n'
run list

printf '\nDemo complete. Nothing was written to ~/.tallowmark/store.json.\n'
