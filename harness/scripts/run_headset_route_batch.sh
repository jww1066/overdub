#!/usr/bin/env bash
# Capture N headset-route timestamp runs back-to-back, for the item-13 (c) headset-route
# timestamp-variance study (prototype-plan.md Test 1a "Interim timestamp-variance plan" step 3).
#
# Drives ConditionSweepTest#headsetRouteCapture via `am instrument`: the reference plays into a
# connected wired/USB headset while the built-in mic records — the exact stream/route shape of a
# product headphone session. Each run logs the getTimestamp-derived stream offset plus the ~11-read
# multi-read series in its sidecar; the offline analysis
# (analysis/scripts/analyze_timestamp_multiread.py) then yields the outlier rate / read-noise std
# on THIS route. There is no acoustic anchor here (no bleed, so the calibration click cannot
# anchor) — honesty still waits for the loopback rig; this batch is variance/outlier statistics
# only.
#
# Operator preconditions, per batch:
#   1. A wired/USB headset connected (the run hard-fails without one — never falls back to the
#      speaker). DO NOT WEAR IT: STREAM_MUSIC is pinned to max, so the reference plays LOUD into
#      the earpieces. Leave it on the desk.
#   2. Phone on battery (the USB port is occupied) — start with a decent charge; ~40 runs is
#      ~15 min. Over Wi-Fi ADB, keep the screen awake if the connection tends to drop in Doze.
#   3. No repositioning needed between runs; the phone can lie untouched for the whole batch.
#
# Files land in the app's files/headset_route dir (NOT files/sweep), timestamped, never
# overwritten:
#   adb pull /sdcard/Android/data/com.overdub.harness/files/headset_route <dest>
#   (MSYS_NO_PATHCONV=1 on Git Bash)
#
# Usage:
#   harness/scripts/run_headset_route_batch.sh <count>
#   harness/scripts/run_headset_route_batch.sh 40
set -uo pipefail

COUNT="${1:-}"
if [[ -z "$COUNT" ]]; then
    echo "usage: $0 <count>" >&2
    exit 2
fi

PKG=com.overdub.harness
RUNNER="$PKG.test/androidx.test.runner.AndroidJUnitRunner"
CLASS=com.overdub.harness.capture.ConditionSweepTest

FAILS=0
for i in $(seq 1 "$COUNT"); do
    echo "===== headset-route run $i/$COUNT ====="
    adb logcat -c
    adb shell am instrument -w -e class "$CLASS#headsetRouteCapture" "$RUNNER"
    INSTR_STATUS=$?
    adb logcat -d -s OverdubSweep:V OverdubHarness:V | grep -E "RESULT|NOTE|stream offset|timestamp samples|===" || true
    if [[ $INSTR_STATUS -ne 0 ]]; then
        FAILS=$((FAILS + 1))
        echo "!!! run $i hard-failed (no headset / XRun / route / no timestamps)"
    fi
done

echo "===== done: $COUNT headset-route runs, $FAILS hard-fails ====="
exit $((FAILS > 0 ? 1 : 0))
