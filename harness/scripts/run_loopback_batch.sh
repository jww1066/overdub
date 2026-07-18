#!/usr/bin/env bash
# Capture N electrical-loopback runs back-to-back, for Test 1 (continuous-buffer scheduling-seam
# stability) and Test 1a (AAudio self-reported latency vs. electrical ground truth) --
# prototype-plan.md "Hardware status".
#
# Drives ConditionSweepTest#electricalLoopbackCapture via `am instrument`: the reference plays out
# through the USB adapter and is read back on the SAME adapter's input line via a PassMark TRRS
# loopback plug -- no acoustic path, no room, no positioning. Each run logs the XRun count, the
# resolved output/input routes, and (if getTimestamp succeeds) the stream-offset plus multi-read
# series in its sidecar. Test 1's pass bar is offset variance across the ~20 reps staying within
# ±3ms with zero XRuns; Test 1a's is the discrepancy between that offset and each rep's
# getTimestamp-derived stream offset staying ≤5ms. Neither bar is evaluated by this script -- it
# only drives captures and surfaces the per-rep logcat feedback; the offline pass/fail judgment
# reads the pulled WAV+JSON pairs.
#
# Operator preconditions, per batch:
#   1. Movo UCMA-2 (or equivalent USB-C-to-TRRS adapter) plugged into the phone's USB-C port, and
#      the PassMark Audio Loopback Plug plugged into the adapter's TRRS jack. The run hard-fails
#      without a USB output AND a USB input device present -- it never falls back to the
#      speaker/built-in mic (CaptureEngine.headsetOutputDeviceId / usbInputDeviceId).
#   2. Verify the adapter enumerates on BOTH sides before the first run:
#        adb shell dumpsys audio | grep -i usb
#      Expect a sink (output) AND a source (input) DeviceInfo/state line for the same card/device.
#   3. Phone on battery (the USB port is occupied by the adapter) -- start with a decent charge.
#   4. No repositioning needed between runs; the phone can lie untouched for the whole batch (this
#      is the point of an electrical rig -- no room noise, no distance/orientation variables).
#
# Files land in the app's files/loopback dir (NOT files/sweep), timestamped, never overwritten:
#   adb pull /sdcard/Android/data/com.overdub.harness/files/loopback <dest>
#   (MSYS_NO_PATHCONV=1 on Git Bash)
#
# Usage:
#   harness/scripts/run_loopback_batch.sh <count>
#   harness/scripts/run_loopback_batch.sh 20
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
    echo "===== loopback run $i/$COUNT ====="
    adb logcat -c
    adb shell am instrument -w -e class "$CLASS#electricalLoopbackCapture" "$RUNNER"
    INSTR_STATUS=$?
    adb logcat -d -s OverdubSweep:V OverdubHarness:V | grep -E "RESULT|NOTE|stream offset|timestamp samples|===" || true
    if [[ $INSTR_STATUS -ne 0 ]]; then
        FAILS=$((FAILS + 1))
        echo "!!! run $i hard-failed (no USB in/out / XRun / route mismatch)"
    fi
done

echo "===== done: $COUNT loopback runs, $FAILS hard-fails ====="
exit $((FAILS > 0 ? 1 : 0))
