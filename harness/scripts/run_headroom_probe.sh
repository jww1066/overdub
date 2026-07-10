#!/usr/bin/env bash
# Run the capture-headroom diagnostic on the connected device: three arms of the same
# physical cell, no repositioning between them (ConditionSweepTest#headroomProbe).
#
#   i16_vr       i16 + VoiceRecognition   -- control; must REPRODUCE the ADC rail
#   float_vr     float32 + VoiceRecognition -- does a wider capture path un-rail it?
#   float_unproc float32 + Unprocessed      -- does the measurement-grade preset un-rail it?
#
# Interpretation (design-summary.md capture-headroom / offline-dsp.md clip census):
#   control rails, float arm doesn't  -> clipping is digital (int16 conversion/gain); headroom
#                                        is recoverable in software.
#   all arms rail                     -> analog front-end saturation; no format change helps.
#   control does NOT rail             -> the level conditions aren't comparable to the Session A
#                                        captures (phone mispositioned / volume off) -- fix the
#                                        setup before believing the float arms.
#
# Physical setup: the baseline cell, canonical wall geometry (same as run_sweep_cell.sh),
# positioned BEFORE calling this. The CLIP CENSUS logcat line per arm is the immediate readout;
# pull files/headroom and run analysis/scripts/census_clipping.py for the authoritative census.
#
# Usage:
#   harness/scripts/run_headroom_probe.sh            # all three arms, in order
#   harness/scripts/run_headroom_probe.sh float_vr   # one arm
#   REFLECTOR_GEOMETRY=<label> ... to override the canonical "wall" (same rule as run_sweep_cell.sh)
#   CONDITION=<id> ... to probe a non-baseline cell
set -uo pipefail

GEOMETRY="${REFLECTOR_GEOMETRY:-wall}"
CONDITION="${CONDITION:-}"

PKG=com.overdub.harness
RUNNER="$PKG.test/androidx.test.runner.AndroidJUnitRunner"
CLASS=com.overdub.harness.capture.ConditionSweepTest

run_arm() {
    local name="$1" fmt="$2" preset="$3"
    echo ">>> headroom arm: $name (capture_format=$fmt input_preset=$preset geometry=$GEOMETRY)"
    adb logcat -c
    local cond_args=()
    [[ -n "$CONDITION" ]] && cond_args=(-e condition "$CONDITION")
    adb shell am instrument -w \
        -e capture_format "$fmt" -e input_preset "$preset" -e reflector_geometry "$GEOMETRY" \
        "${cond_args[@]}" \
        -e class "$CLASS#headroomProbe" "$RUNNER"
    local status=$?
    echo "--- logcat ($name) ---"
    adb logcat -d -s OverdubSweep:V OverdubHarness:V | grep -E "RESULT|SANITY|CLIP CENSUS|NOTE|===|format" || true
    if [[ $status -ne 0 ]]; then
        echo "!!! arm $name hard-failed (am instrument status $status) -- fix and retry before the next arm"
    fi
    return $status
}

ARM="${1:-all}"
case "$ARM" in
    i16_vr)       run_arm i16_vr i16 voice_recognition ;;
    float_vr)     run_arm float_vr float32 voice_recognition ;;
    float_unproc) run_arm float_unproc float32 unprocessed ;;
    all)
        run_arm i16_vr i16 voice_recognition || exit $?
        run_arm float_vr float32 voice_recognition || exit $?
        run_arm float_unproc float32 unprocessed || exit $?
        echo ">>> all arms done. Pull with:"
        echo "    adb pull /sdcard/Android/data/$PKG/files/headroom <dest>"
        echo "    then: analysis/.venv/Scripts/python analysis/scripts/census_clipping.py <dest>/*.wav"
        ;;
    *) echo "usage: $0 [i16_vr|float_vr|float_unproc|all]" >&2; exit 2 ;;
esac
