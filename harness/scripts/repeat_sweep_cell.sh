#!/usr/bin/env bash
# Capture the SAME condition-sweep cell N times back-to-back, for the item-10 stream-timestamp
# decomposition study (test2-step2-plan.md item 10 / doc/guides/offline-dsp.md
# "run-to-run spread can be a measurement artifact").
#
# Repeating one cell with NO physical repositioning holds the acoustic round-trip constant, so any
# run-to-run variation in the GCC-PHAT offset is per-session harness start-jitter. Each capture logs
# its own getTimestamp-derived stream_offset_ms; the offline decomposition
# (analysis/scripts/decompose_offset.py) then checks whether subtracting it collapses the run-to-run
# spread (=> jitter, benign) or not (=> real misalignment).
#
# Each run writes a fresh {condition_id}_{timestamp}.{wav,json} to the device sweep dir (timestamped,
# so runs never overwrite each other). Pull them afterward with adb (MSYS_NO_PATHCONV=1 on Git Bash).
#
# Usage:
#   harness/scripts/repeat_sweep_cell.sh <condition_id> <count>
#   harness/scripts/repeat_sweep_cell.sh conversational_armslength_faceup_none 8
set -uo pipefail

COND="${1:-}"
COUNT="${2:-}"
if [[ -z "$COND" || -z "$COUNT" ]]; then
    echo "usage: $0 <condition_id> <count>" >&2
    exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILS=0
for i in $(seq 1 "$COUNT"); do
    echo "===== repeat $i/$COUNT: $COND ====="
    bash "$HERE/run_sweep_cell.sh" "$COND"
    if [[ $? -ne 0 ]]; then
        FAILS=$((FAILS + 1))
        echo "!!! repeat $i hard-failed"
    fi
done

echo "===== done: $COUNT runs of $COND, $FAILS hard-fails ====="
exit $((FAILS > 0 ? 1 : 0))
