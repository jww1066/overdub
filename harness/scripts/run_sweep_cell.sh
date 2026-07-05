#!/usr/bin/env bash
# Run ONE condition-sweep cell on the connected device and print its RESULT line.
#
# Drives ConditionSweepTest#sweepOneCondition via `am instrument` (NOT `gradlew
# connectedAndroidTest`, which uninstalls-and-wipes the captures on completion --
# see test2-step2-plan.md Components Sec 4). Clears logcat first, runs the cell,
# then dumps the OverdubSweep tag so the operator sees the RMS/XRun/route feedback
# that is the relied-upon channel for a facedown/pocketed phone.
#
# The physical positioning for the cell is the operator's job and must be done
# BEFORE calling this. am instrument's own pass/fail (hard-fails on XRun / ring
# overflow / non-speaker route) is the reposition-and-retry signal; a sub-floor RMS
# is logged as a NOTE, not a failure.
#
# Usage:
#   harness/scripts/run_sweep_cell.sh <condition_id>
#   harness/scripts/run_sweep_cell.sh conversational_armslength_faceup_none
#   harness/scripts/run_sweep_cell.sh --list      # dump the 36 valid ids
set -uo pipefail

PKG=com.overdub.harness
RUNNER="$PKG.test/androidx.test.runner.AndroidJUnitRunner"
CLASS=com.overdub.harness.capture.ConditionSweepTest

if [[ "${1:-}" == "--list" ]]; then
    adb logcat -c
    adb shell am instrument -w -e class "$CLASS#listConditionIds" "$RUNNER" >/dev/null 2>&1
    adb logcat -d -s OverdubSweep:I | grep "condition id:"
    exit 0
fi

COND="${1:-}"
if [[ -z "$COND" ]]; then
    echo "usage: $0 <condition_id>   (or --list)" >&2
    exit 2
fi

echo ">>> cell: $COND"
adb logcat -c
adb shell am instrument -w -e condition "$COND" -e class "$CLASS#sweepOneCondition" "$RUNNER"
INSTR_STATUS=$?

echo "--- OverdubSweep logcat ---"
# -s with one tag spec per tag (two specs on the SAME tag collapse to the last one's
# level, e.g. "OverdubSweep:I OverdubSweep:W" silently filters down to W only and drops
# the Info-level RESULT line). Use a single Verbose spec per tag. OverdubHarness carries
# the SANITY line; OverdubSweep carries RESULT/NOTE/===.
adb logcat -d -s OverdubSweep:V OverdubHarness:V | grep -E "RESULT|SANITY|NOTE|===" || true

if [[ $INSTR_STATUS -ne 0 ]]; then
    echo "!!! am instrument returned $INSTR_STATUS -- treat as a hard-fail (reposition and retry this cell)"
fi
exit $INSTR_STATUS
