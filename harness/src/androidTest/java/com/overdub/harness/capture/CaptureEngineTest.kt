package com.overdub.harness.capture

import android.Manifest
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import com.overdub.harness.condition.BASELINE_CONDITION
import com.overdub.harness.metadata.conditionMetadataFromJson
import com.overdub.harness.wav.WavAudio
import com.overdub.harness.wav.WavFormat
import com.overdub.harness.wav.readWav
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import kotlin.math.PI
import kotlin.math.sin

/**
 * Tier-2 instrumented tests (test2-step2-plan.md) for the full-duplex capture engine, run on a real
 * Pixel 10 against real Oboe/AudioRecord/AudioTrack — no mocks, per CLAUDE.md. These assert
 * wiring/state-machine correctness and that bleed reaches the mic at all; they do NOT judge audio
 * quality or the GCC-PHAT pass bar (that is Tier 3).
 *
 * Each capture injects a short synthetic tone (see [shortReference]) so a run finishes in ~1s rather
 * than the 15s bundled asset; the acoustic path (speaker -> air -> mic) is still real.
 *
 * Storage isolation (CLAUDE.md "Instrumented test isolation"): every capture is written under a
 * dedicated cache subdirectory, never the app's real capture output, so running this suite cannot
 * clobber real data. Side effect worth noting: each run pins the device's STREAM_MUSIC volume to
 * max, so the suite will raise the phone's media volume.
 */
@RunWith(AndroidJUnit4::class)
class CaptureEngineTest {

    @get:Rule
    val recordPermission: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)

    private lateinit var context: Context
    private lateinit var engine: CaptureEngine
    private lateinit var outputDir: File

    @Before
    fun setUp() {
        context = InstrumentationRegistry.getInstrumentation().targetContext
        engine = CaptureEngine(context)
        outputDir = File(context.cacheDir, "capture_test").apply {
            deleteRecursively()
            mkdirs()
        }
    }

    /** A 1-second mono sine at the device's native rate, so duration/format math is exact. */
    private fun shortReference(): WavAudio {
        val rate = engine.nativeOutputSampleRate()
        val samples = ShortArray(rate) { i ->
            (8000.0 * sin(2.0 * PI * 440.0 * i / rate)).toInt().toShort()
        }
        return WavAudio(WavFormat(rate, 16, 1), samples)
    }

    private fun capture() = engine.runCapture(BASELINE_CONDITION, outputDir, shortReference())

    @Test
    fun fullDuplexStreamOpensAndCaptures() {
        val result = capture()
        // No CaptureException means both streams opened + started in LowLatency/Exclusive.
        assertTrue("expected captured samples, got ${result.capturedSampleCount}", result.capturedSampleCount > 0)
    }

    @Test
    fun zeroXRunsDuringCapture() {
        val result = capture()
        // Hard fail, same bar as Test 1: an underrun invalidates the capture's data.
        assertEquals("XRun count must be zero", 0, result.xrunCount)
        assertEquals("ring must not have overflowed", 0L, result.droppedFrameCount)
    }

    @Test
    fun capturedDurationMatchesPlayback() {
        val result = capture()
        val playbackMs = 1000L // shortReference() is exactly 1s
        val capturedMs = result.capturedSampleCount * 1000L / result.sampleRate
        // Capture spans stream-start to stop: playback (~1s) + tail + warmup/drain. Bound it loosely
        // both ways — the point is it isn't wildly short (truncated) or long (runaway).
        assertTrue(
            "captured ${capturedMs}ms not within tolerance of ${playbackMs}ms playback",
            capturedMs in (playbackMs / 2)..(playbackMs + 2000L),
        )
    }

    @Test
    fun capturedIsNonSilent() {
        val result = capture()
        // The real acoustic assertion: the tone played through the speaker reached the mic.
        assertTrue("capture was silent (rms=${result.rms})", result.sanityGatePassed)
    }

    @Test
    fun capturedFormatMatchesNativeRate() {
        val result = capture()
        assertEquals("stream rate must be the device native rate", engine.nativeOutputSampleRate(), result.sampleRate)
        val decoded = readWav(result.wavFile.readBytes())
        assertEquals(result.sampleRate, decoded.format.sampleRate)
        assertEquals(16, decoded.format.bitDepth)
        assertEquals(1, decoded.format.channelCount)
    }

    @Test
    fun metadataTaggedEndToEnd() {
        val result = capture()
        assertTrue("json sidecar not written", result.jsonFile.exists())
        val meta = conditionMetadataFromJson(result.jsonFile.readText())
        assertEquals(BASELINE_CONDITION.conditionId, meta.conditionId)
        assertEquals(BASELINE_CONDITION.volume.gainFraction, meta.playbackVolume, 0.0001)
        assertEquals(BASELINE_CONDITION.distance.approxCm, meta.distanceCm)
        assertEquals(BASELINE_CONDITION.orientation.label, meta.orientation)
        assertEquals(BASELINE_CONDITION.obstruction.label, meta.obstruction)
        assertEquals("voice_recognition", meta.inputPreset)
        assertEquals(result.sampleRate, meta.sampleRate)
        assertEquals(0, meta.xrunCount)
        assertTrue("device model should be populated", !meta.deviceModel.isNullOrBlank())
        assertTrue("stream volume index should be logged", meta.streamVolumeIndex != null)
    }

    @Test
    fun speakerRouteHolds() {
        // With no headset connected this confirms the default speaker path; the override against
        // an ACTIVE headset is speakerRouteOverrideHoldsWithHeadsetConnected below (manual
        // precondition: plug the headset in first).
        val result = capture()
        assertTrue("output route was ${result.outputRoute}, expected the built-in speaker", result.routeIsBuiltinSpeaker)
    }

    @Test
    fun speakerRouteOverrideHoldsWithHeadsetConnected() {
        // The Tier-2 headset-override variant (test2-step2-plan.md): with a headset physically
        // connected — the manual precondition — does setDeviceId()'s speaker/mic forcing demote
        // the active headset route for this stream? This is the gating fact for the
        // forced-speaker-chirp headphone design (design-summary.md "Headphone monitoring gap").
        // Skips (assumption failure) rather than fails when no headset is present, so the default
        // suite stays green without one.
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val headsetTypes = setOf(
            AudioDeviceInfo.TYPE_USB_HEADSET,
            AudioDeviceInfo.TYPE_USB_DEVICE,
            AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
        )
        val headsets = audioManager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            .filter { it.type in headsetTypes }
        assumeTrue(
            "headset-override test needs a headset connected before the run; none found",
            headsets.isNotEmpty(),
        )

        val result = capture()
        assertTrue(
            "override FAILED: output route was ${result.outputRoute} with " +
                "${headsets.map { "${it.productName}(type=${it.type})" }} connected",
            result.routeIsBuiltinSpeaker,
        )
        // Corroborate acoustically: if audio really left the built-in speaker, the built-in mic
        // hears it. A silent capture with a speaker-claiming route would mean the route metadata
        // lies (audio actually went to the headset) — the failure mode route logging alone misses.
        assertTrue(
            "route claims builtin speaker but capture was silent (rms=${result.rms}) — " +
                "audio likely went to the headset despite the reported route",
            result.sanityGatePassed,
        )
    }

    @Test
    fun backToBackRunsNoLeakOrCrash() {
        // A human runs this dozens of times across the real matrix; a leak surfacing on run 15 would
        // otherwise read as a confusing mid-sweep failure. Assert streams open/close cleanly each time.
        val runs = 5
        repeat(runs) { i ->
            val result = capture()
            assertTrue("run $i produced no samples", result.capturedSampleCount > 0)
            assertEquals("run $i had XRuns", 0, result.xrunCount)
            assertTrue("run $i wav missing", result.wavFile.exists())
        }
    }
}
