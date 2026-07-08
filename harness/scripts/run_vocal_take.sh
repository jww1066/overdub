#!/usr/bin/env bash
# Record ONE close-mic vocal take on the connected device (test2-step2-plan.md item 12).
#
# Drives ConditionSweepTest#recordVocalTake via `am instrument`: the exact sweep capture pipeline
# (same mic, same VoiceRecognition preset -- so the take's RMS is in the SAME measurement basis as
# the sweep captures' bleed RMS for the ratio-pinning step) but with playback gain 0.0, so the
# phone's speaker emits silence and the take carries zero reference bleed.
#
# Operator protocol, per capture (~16s each; run 3-4 times for independent slices):
#   1. Start the reference playing on a DIFFERENT device (laptop/second phone) into wired or
#      sealed headphones at modest volume -- headphone leakage into this phone's mic would inject a
#      copy of the reference at an unknown offset and silently corrupt the study. Monitor the
#      CLICK-BEARING asset (harness/src/main/assets/reference_track.wav), NOT boots.wav: the vet
#      script's click gate can only certify "no leak" if the audio being monitored contains the
#      click (learned from take 1, which monitored boots.wav and voided that gate).
#   2. Hold this phone close-mic (~10 cm mouth-to-mic), NO headset connected to it.
#   3. Trigger this script and perform in time with the reference, continuously, from before the
#      "PERFORM NOW" logcat line until the RESULT line appears -- gaps of silence make the eventual
#      injection test easier than production.
#   4. Watch the RESULT line: a silent take hard-fails (retry); watch for clipping separately when
#      inspecting the pulled WAV (analysis/scripts/inspect_wav.py) -- close-mic plosives clip easily
#      and clipping cannot be scaled away afterward.
#
# Files land in the app's files/vocal dir (NOT files/sweep), timestamped, never overwritten:
#   adb pull /sdcard/Android/data/com.overdub.harness/files/vocal <dest>   (MSYS_NO_PATHCONV=1 on Git Bash)
#
# Usage:
#   harness/scripts/run_vocal_take.sh
set -uo pipefail

PKG=com.overdub.harness
RUNNER="$PKG.test/androidx.test.runner.AndroidJUnitRunner"
CLASS=com.overdub.harness.capture.ConditionSweepTest

echo ">>> vocal take: playback gain 0.0 (record-only); perform close-mic, in time with the"
echo ">>> reference monitored on ANOTHER device's headphones, for the full ~16s capture"
adb logcat -c
adb shell am instrument -w -e class "$CLASS#recordVocalTake" "$RUNNER"
INSTR_STATUS=$?

echo "--- OverdubSweep logcat ---"
adb logcat -d -s OverdubSweep:V OverdubHarness:V | grep -E "RESULT|SANITY|NOTE|===" || true

if [[ $INSTR_STATUS -ne 0 ]]; then
    echo "!!! am instrument returned $INSTR_STATUS -- take invalid (silent/XRun/route), retry"
fi
exit $INSTR_STATUS
