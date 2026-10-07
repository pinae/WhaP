#!/usr/bin/env bash
# One unattended run of the end-to-end suite, for a timer (see README.md).
#
# Each run gets a dated directory under WHAP_E2E_RESULTS: the pytest output,
# a JUnit report, and test-results/ with the traces, screenshots, job logs
# and docker logs of every failure. `latest` points at the newest run; runs
# older than WHAP_E2E_KEEP_DAYS are removed. Exits with pytest's status, so a
# failed run is a failed unit. Extra arguments go to pytest, e.g. --matrix full;
# give the rig as --rig=PATH or WHAP_E2E_RIG (see ../README.md).
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS="${WHAP_E2E_RESULTS:-$HOME/whap-e2e-results}"
KEEP_DAYS="${WHAP_E2E_KEEP_DAYS:-14}"
RUN="$RESULTS/$(date +%Y-%m-%d_%H%M)"

mkdir -p "$RUN"
ln -sfn "$RUN" "$RESULTS/latest"
cd "$E2E_DIR"
uv sync --frozen --quiet

status=0
uv run pytest --output "$RUN/test-results" --junitxml "$RUN/junit.xml" -rfEs "$@" \
    > "$RUN/pytest.log" 2>&1 || status=$?

# The last line pytest prints, e.g. "== 40 passed, 2 failed in 3812.20s ==".
summary="$(tail -n 1 "$RUN/pytest.log")"
echo "$summary" > "$RUN/summary.txt"
echo "whap e2e: exit $status: $summary (results in $RUN)"

find "$RESULTS" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
exit "$status"
