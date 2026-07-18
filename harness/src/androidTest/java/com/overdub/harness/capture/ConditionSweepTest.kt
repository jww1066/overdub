package com.overdub.harness.capture

import android.Manifest
import android.content.Context
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import com.overdub.harness.condition.BASELINE_CONDITION
import com.overdub.harness.condition.Condition
import com.overdub.harness.condition.conditionFromId
import com.overdub.harness.condition.generateConditionMatrix
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

private const val TAG = "OverdubSweep"

/**
 * Condition-sweep driver (test2-step2-plan.md Components §3, "Next steps" item 3). Where
 * [CaptureEngineTest] asserts wiring correctness on a short synthetic tone, this drives ONE real
 * capture of the bundled reference track per invocation for the condition named by the `condition`
 * instrumentation argument, and writes the WAV+JSON into a persistent app-private external directory
 * rather than a wiped cache dir — this is the real sweep *data*, not a self-checking test fixture.
 *
 * The output dir is directly `adb pull`-able (verified on the Pixel 10, 2026-07-05:
 * `adb pull /sdcard/Android/data/com.overdub.harness/files/sweep`). The one operational gotcha:
 * `gradlew connectedAndroidTest` UNINSTALLS the app on completion, which wipes app-private storage and
 * deletes the captures — so drive the real sweep with `am instrument` against a persistently installed
 * app+test APK (the command above), not the gradle connected-test task, or the data is gone before it
 * can be pulled.
 *
 * One invocation == one matrix cell, on purpose: the physical positioning (distance / orientation /
 * obstruction, per Components §3's "Physical setup and positioning protocol") is a manual step the
 * operator performs *before* triggering the run, and a @Parameterized loop can't reposition the phone
 * between cells. Drive the full 36-cell matrix by invoking once per cell, e.g.:
 *
 *   adb shell am instrument -w \
 *     -e condition quiet_near_faceup_none \
 *     -e class com.overdub.harness.capture.ConditionSweepTest#sweepOneCondition \
 *     com.overdub.harness.test/androidx.test.runner.AndroidJUnitRunner
 *
 * With no `condition` argument it runs the baseline realistic cell (a sensible single-run default).
 * Enumerate the 36 valid ids by running the [listConditionIds] method and reading logcat.
 *
 * Failure semantics follow the plan. XRun / ring-overflow contamination and a non-speaker output
 * route are HARD failures — a signal to the operator to reposition and retry that cell. The
 * contaminated file is still written (timestamped, with the flags recorded in its JSON sidecar), so
 * nothing is silently fed into analysis as if it were clean. A capture that merely falls below the
 * RMS sanity floor is NOT a failure: an edge cell (quiet / far / pocketed) reading as no-bleed is an
 * acceptable, expected outcome and is itself the finding (prototype-plan.md: "Edge conditions failing
 * is acceptable and becomes a documented UX constraint").
 *
 * Prerequisite: a real `reference_track.wav` asset at the device's native sample rate must be present
 * (harness/scripts/generate_reference_track.py produces the synthetic placeholder; swap in a real dry
 * beatbox recording before a *trusted* Tier-3 sweep — "Next steps" item 5). The bundled asset is
 * loaded by default; a rate mismatch is warned, not silently resampled.
 */
@RunWith(AndroidJUnit4::class)
class ConditionSweepTest {

    @get:Rule
    val recordPermission: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)

    private lateinit var context: Context
    private lateinit var engine: CaptureEngine
    private lateinit var outputDir: File

    @Before
    fun setUp() {
        context = InstrumentationRegistry.getInstrumentation().targetContext
        engine = CaptureEngine(context)
        // Persistent app-private external storage (Components §2), adb-pullable, and deliberately NOT
        // wiped by us: retries and successive cells accumulate here, deduplicated by the timestamped
        // filenames rather than by clearing the directory (a retry must never overwrite a prior
        // attempt). Caveat in the class KDoc: `gradlew connectedAndroidTest` uninstalls-and-wipes on
        // completion, so run the real sweep via `am instrument`, not that task.
        outputDir = File(context.getExternalFilesDir(null), "sweep").apply { mkdirs() }
    }

    @Test
    fun sweepOneCondition() {
        val arg = InstrumentationRegistry.getArguments().getString("condition")
        val condition = resolveCondition(arg)

        // Item 9: record the physical geometry the distance axis was measured against, so a
        // desk-vs-wall style contamination is readable from the sidecar instead of silent. A missing
        // argument is recorded as null (= unknown) and warned about — never defaulted to a claimed
        // geometry the operator didn't assert. run_sweep_cell.sh passes the canonical "wall".
        val reflectorGeometry =
            InstrumentationRegistry.getArguments().getString("reflector_geometry")?.takeIf { it.isNotBlank() }
        if (reflectorGeometry == null) {
            Log.w(
                TAG,
                "NOTE no `reflector_geometry` argument — sidecar will record it as unknown; " +
                    "pass -e reflector_geometry <label> (canonical sweep value: wall)",
            )
        }

        Log.i(
            TAG,
            "=== sweeping ${condition.conditionId} (${describe(condition)}) " +
                "geometry=${reflectorGeometry ?: "UNKNOWN"} ===",
        )
        Log.i(TAG, "output dir (adb pull this): ${outputDir.absolutePath}")

        val result = engine.runCapture(condition, outputDir, reflectorGeometry = reflectorGeometry)

        Log.i(
            TAG,
            "RESULT ${condition.conditionId}: rms=%.1f sanity=%s xrun=%d dropped=%d route=%s rate=%dHz file=%s"
                .format(
                    result.rms,
                    if (result.sanityGatePassed) "PASS" else "FAIL",
                    result.xrunCount,
                    result.droppedFrameCount,
                    result.outputRoute,
                    result.sampleRate,
                    result.wavFile.name,
                ),
        )

        // Hard fails: contamination that invalidates the capture regardless of condition. The file is
        // already written and flagged; failing here tells the operator to reposition-and-retry.
        assertEquals("XRun during capture invalidates this cell — reposition and retry", 0, result.xrunCount)
        assertEquals("ring overflow dropped captured samples — retry", 0L, result.droppedFrameCount)
        assertTrue(
            "output route was ${result.outputRoute}, not the built-in speaker — disconnect any headset and retry",
            result.routeIsBuiltinSpeaker,
        )

        // Deliberately NOT asserted: sanityGatePassed. A quiet/far/pocketed cell reading below the
        // bleed floor is acceptable data, not a test failure — it is logged above and recorded in the
        // JSON sidecar's RMS for the offline GCC-PHAT pass to judge against the pass bar.
        if (!result.sanityGatePassed) {
            Log.w(
                TAG,
                "NOTE ${condition.conditionId} fell below the RMS sanity floor — recorded as an " +
                    "(expected-for-edge-cells) finding, not a failure",
            )
        }
    }

    @Test
    fun recordVocalTake() {
        // Item-12 record-only mode: identical full-duplex pipeline and input chain as a sweep cell
        // (same mic, same VoiceRecognition preset -- the point, so the take's RMS is in the same
        // measurement basis as the bleed RMS it will be ratio'd against), but playback gain 0.0, so
        // the speaker emits silence and the take carries ZERO reference bleed. The performer monitors
        // the reference on headphones from a DIFFERENT device and performs close-mic into this one
        // for the full capture (~16s). Output goes to files/vocal, not files/sweep -- these are not
        // sweep data and must never be swept up by a sweep-dir pull/analysis.
        val vocalDir = File(context.getExternalFilesDir(null), "vocal").apply { mkdirs() }
        Log.i(TAG, "=== vocal take: recording ~16s, playback gain 0.0 (record-only) -- PERFORM NOW ===")
        Log.i(TAG, "output dir (adb pull this): ${vocalDir.absolutePath}")

        val result = engine.runCapture(VOCAL_TAKE_SPEC, vocalDir)

        Log.i(
            TAG,
            "RESULT ${VOCAL_TAKE_SPEC.captureId}: rms=%.1f sanity=%s xrun=%d dropped=%d route=%s rate=%dHz file=%s"
                .format(
                    result.rms,
                    if (result.sanityGatePassed) "PASS" else "FAIL",
                    result.xrunCount,
                    result.droppedFrameCount,
                    result.outputRoute,
                    result.sampleRate,
                    result.wavFile.name,
                ),
        )

        assertEquals("XRun during the take invalidates it — retry", 0, result.xrunCount)
        assertEquals("ring overflow dropped samples — retry", 0L, result.droppedFrameCount)
        assertTrue(
            "output route was ${result.outputRoute}, not the built-in speaker — disconnect any headset " +
                "from THIS phone (monitor on the other device) and retry",
            result.routeIsBuiltinSpeaker,
        )
        // Unlike a sweep edge cell, a silent vocal take carries no finding — it just means the
        // performer wasn't performing. Hard-fail so the operator retries.
        assertTrue(
            "vocal take was silent (rms=${result.rms}) — perform during the capture and retry",
            result.sanityGatePassed,
        )
    }

    @Test
    fun headsetRouteCapture() {
        // Item-13 (c) headset-route timestamp study (prototype-plan.md Test 1a interim step 3):
        // the reference plays into a connected wired/USB headset (manual precondition — the
        // engine hard-fails if none is connected) while the built-in mic records, the exact
        // stream/route shape of a product headphone session. The data is the per-stream
        // getTimestamp statistics on this route; the mic hears only the room, so a sub-floor RMS
        // is EXPECTED and not asserted, and the calibration click cannot anchor. Output goes to
        // files/headset_route, never files/sweep — these are not bleed data.
        val routeDir = File(context.getExternalFilesDir(null), "headset_route").apply { mkdirs() }
        Log.i(TAG, "=== headset-route capture (~16s): reference -> headset, builtin mic recording ===")
        Log.i(TAG, "output dir (adb pull this): ${routeDir.absolutePath}")

        val result = engine.runCapture(HEADSET_ROUTE_SPEC, routeDir)

        Log.i(
            TAG,
            ("RESULT ${HEADSET_ROUTE_SPEC.captureId}: rms=%.1f xrun=%d dropped=%d route=%s rate=%dHz " +
                "stream_offset_ms=%s ts_reads=%d file=%s")
                    .format(
                        result.rms,
                        result.xrunCount,
                        result.droppedFrameCount,
                        result.outputRoute,
                        result.sampleRate,
                        result.streamOffsetMs?.let { "%.2f".format(it) } ?: "UNAVAILABLE",
                        result.timestampSamples?.size ?: 0,
                        result.wavFile.name,
                    ),
        )

        assertEquals("XRun during capture invalidates this run — retry", 0, result.xrunCount)
        assertEquals("ring overflow dropped samples — retry", 0L, result.droppedFrameCount)
        // The route must actually BE the headset — a capture that fell back to the speaker is
        // measuring the wrong route and must not enter the batch.
        assertTrue(
            "output route was ${result.outputRoute}, expected the headset — check the connection and retry",
            !result.routeIsBuiltinSpeaker,
        )
        // Timestamps ARE the measurement here; a run without them carries no data at all.
        assertTrue(
            "getTimestamp unavailable — no timestamp data captured, nothing to measure",
            result.streamOffsetMs != null,
        )
    }

    @Test
    fun electricalLoopbackCapture() {
        // Test 1 / Test 1a (prototype-plan.md "Hardware status"): the reference plays out through
        // the USB adapter and is read back on the SAME adapter's input line via a PassMark TRRS
        // loopback plug -- no acoustic path, no room, no positioning. The engine hard-fails if
        // either a USB output or a USB input device isn't present (CaptureEngine.usbInputDeviceId /
        // headsetOutputDeviceId), so a run that completes at all already confirms the rig is wired
        // correctly. Output goes to files/loopback, never files/sweep -- this is not bleed data.
        //
        // Optional `-e capture_format`/`-e input_preset` args (same vocabulary as [headroomProbe])
        // let the operator A/B the input gain path directly on the rig -- e.g. the first real run
        // measured peak=0.0012 FS (~-58 dBFS) on the canonical i16/voice_recognition arm, quiet
        // enough to warrant checking whether UNPROCESSED's HAL gain path reads the electrical
        // signal any hotter before trusting a 20-rep batch to either preset.
        val fmtArg = InstrumentationRegistry.getArguments().getString("capture_format")
        val captureFloat = when (fmtArg) {
            null -> LOOPBACK_SPEC.captureFloat
            "float32", "float" -> true
            "i16" -> false
            else -> throw IllegalArgumentException("unknown capture_format '$fmtArg' (i16|float32)")
        }
        val presetArg = InstrumentationRegistry.getArguments().getString("input_preset")
        val preset = if (presetArg == null) {
            LOOPBACK_SPEC.inputPreset
        } else {
            CaptureInputPreset.entries.firstOrNull { it.label == presetArg }
                ?: throw IllegalArgumentException(
                    "unknown input_preset '$presetArg' (${CaptureInputPreset.entries.joinToString("|") { it.label }})",
                )
        }
        val spec = LOOPBACK_SPEC.copy(
            captureId = "loopback_${if (captureFloat) "float32" else "i16"}_${preset.label}",
            captureFloat = captureFloat,
            inputPreset = preset,
        )

        val loopbackDir = File(context.getExternalFilesDir(null), "loopback").apply { mkdirs() }
        Log.i(TAG, "=== electrical loopback capture: USB out -> USB in via PassMark plug (${spec.captureId}) ===")
        Log.i(TAG, "output dir (adb pull this): ${loopbackDir.absolutePath}")

        val result = engine.runCapture(spec, loopbackDir)

        Log.i(
            TAG,
            ("RESULT ${spec.captureId}: rms=%.1f peak=%.6fFS xrun=%d dropped=%d out_route=%s in_route=%s " +
                "rate=%dHz stream_offset_ms=%s ts_reads=%d file=%s")
                    .format(
                        result.rms,
                        result.peakAbs,
                        result.xrunCount,
                        result.droppedFrameCount,
                        result.outputRoute,
                        result.inputRoute,
                        result.sampleRate,
                        result.streamOffsetMs?.let { "%.2f".format(it) } ?: "UNAVAILABLE",
                        result.timestampSamples?.size ?: 0,
                        result.wavFile.name,
                    ),
        )

        // Any underrun invalidates the continuous-stream assumption Test 1 exists to check
        // (prototype-plan.md Test 1 pass/fail threshold) -- hard fail, not just a logged flag.
        assertEquals("XRun during capture invalidates this rep — retry", 0, result.xrunCount)
        assertEquals("ring overflow dropped samples — retry", 0L, result.droppedFrameCount)
        assertTrue(
            "output route was ${result.outputRoute}, expected the USB adapter — check the connection and retry",
            !result.routeIsBuiltinSpeaker,
        )
        assertTrue(
            "input route was ${result.inputRoute}, expected the USB adapter — check the PassMark plug and retry",
            result.routeIsUsbInput,
        )
    }

    @Test
    fun headroomProbe() {
        // Capture-headroom diagnostic (the ADC-rail finding, doc/guides/offline-dsp.md "census raw
        // captures"): one capture of the named condition (default: baseline cell) with the capture
        // format / input preset named by instrumentation args, so the three arms
        //   i16 + voice_recognition   (control — must REPRODUCE the rail, ~1e3 railed samples)
        //   float32 + voice_recognition (does a wider capture path un-rail the same signal?)
        //   float32 + unprocessed       (does the measurement-grade HAL gain path un-rail it?)
        // are runnable back-to-back with no repositioning. Output goes to files/headroom, never
        // files/sweep — probe files must not enter sweep analysis (distinct captureId enforces the
        // same thing in the sidecar). The CLIP CENSUS logcat line is the immediate readout; the
        // offline judge is analysis/scripts/census_clipping.py on the pulled files.
        val fmtArg = InstrumentationRegistry.getArguments().getString("capture_format") ?: "float32"
        val captureFloat = when (fmtArg) {
            "float32", "float" -> true
            "i16" -> false
            else -> throw IllegalArgumentException("unknown capture_format '$fmtArg' (i16|float32)")
        }
        val presetArg = InstrumentationRegistry.getArguments().getString("input_preset") ?: "voice_recognition"
        val preset = CaptureInputPreset.entries.firstOrNull { it.label == presetArg }
            ?: throw IllegalArgumentException(
                "unknown input_preset '$presetArg' (${CaptureInputPreset.entries.joinToString("|") { it.label }})",
            )
        val condition = resolveCondition(InstrumentationRegistry.getArguments().getString("condition"))
        val reflectorGeometry =
            InstrumentationRegistry.getArguments().getString("reflector_geometry")?.takeIf { it.isNotBlank() }

        val spec = condition.toHeadroomProbeSpec(captureFloat = captureFloat, inputPreset = preset)
        val probeDir = File(context.getExternalFilesDir(null), "headroom").apply { mkdirs() }
        Log.i(TAG, "=== headroom probe: ${spec.captureId} (${describe(condition)}) geometry=${reflectorGeometry ?: "UNKNOWN"} ===")
        Log.i(TAG, "output dir (adb pull this): ${probeDir.absolutePath}")

        val result = engine.runCapture(spec, probeDir, reflectorGeometry = reflectorGeometry)

        Log.i(
            TAG,
            ("RESULT ${spec.captureId}: rms=%.1f peak=%.6fFS railed=%d xrun=%d dropped=%d " +
                "route=%s rate=%dHz format=%s file=%s")
                .format(
                    result.rms,
                    result.peakAbs,
                    result.railedSampleCount,
                    result.xrunCount,
                    result.droppedFrameCount,
                    result.outputRoute,
                    result.sampleRate,
                    result.captureFormat,
                    result.wavFile.name,
                ),
        )

        assertEquals("XRun during capture invalidates this arm — retry", 0, result.xrunCount)
        assertEquals("ring overflow dropped captured samples — retry", 0L, result.droppedFrameCount)
        assertTrue(
            "output route was ${result.outputRoute}, not the built-in speaker — disconnect any headset and retry",
            result.routeIsBuiltinSpeaker,
        )
        // A silent probe carries no headroom data at all (unlike a sweep edge cell, where
        // silence IS the finding) — hard-fail so the operator repositions and retries.
        assertTrue(
            "probe capture was silent (rms=${result.rms}) — check speaker volume/positioning and retry",
            result.sanityGatePassed,
        )
        // Railed count is deliberately NOT asserted either way: the control arm SHOULD rail and
        // the float arms answering "does it?" is the experiment — both outcomes are data.
    }

    @Test
    fun listConditionIds() {
        // Operator convenience: dump all 36 valid `-e condition <id>` values to logcat.
        Log.i(TAG, "=== 36 valid condition ids for -e condition <id> ===")
        generateConditionMatrix().forEach {
            Log.i(TAG, "condition id: ${it.conditionId}${if (it.isBaseline) "  (baseline)" else ""}")
        }
    }

    private fun resolveCondition(arg: String?): Condition {
        if (arg.isNullOrBlank()) {
            Log.i(TAG, "no `condition` argument -> defaulting to the baseline realistic cell")
            return BASELINE_CONDITION
        }
        return conditionFromId(arg)
            ?: throw IllegalArgumentException(
                "unknown condition id '$arg' — run the listConditionIds method for the 36 valid ids",
            )
    }

    private fun describe(c: Condition): String =
        "vol=${c.volume.label}/${c.volume.gainFraction} dist=${c.distance.approxCm}cm " +
            "orient=${c.orientation.label} obstruction=${c.obstruction.label}"
}
