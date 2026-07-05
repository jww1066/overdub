package com.overdub.harness.capture

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.util.Log
import com.overdub.harness.NativeBridge
import com.overdub.harness.condition.Condition
import com.overdub.harness.dsp.rms
import com.overdub.harness.metadata.ConditionMetadata
import com.overdub.harness.metadata.toJson
import com.overdub.harness.wav.WavFormat
import com.overdub.harness.wav.readWav
import com.overdub.harness.wav.writeWav
import java.io.File

private const val TAG = "OverdubHarness"

/** Default bundled reference-track asset (a synthetic placeholder until a real recording is swapped in). */
private const val REFERENCE_TRACK_ASSET = "reference_track.wav"

/**
 * Below this captured RMS (int16 scale), the on-device sanity gate treats the run as "no bleed
 * reached the mic." A coarse smoke threshold, not a quality bar -- the real quality/pass judgment is
 * Tier 3's manual + GCC-PHAT analysis. Tunable once real captures show typical baseline levels.
 */
private const val RMS_SANITY_FLOOR = 50.0

/** Extra capture tail after playback completes, so bleed decay isn't clipped off the end. */
private const val CAPTURE_TAIL_MS = 200L

/** Safety margin on top of the reference track's own duration before the poll loop gives up. */
private const val PLAYBACK_TIMEOUT_MARGIN_MS = 2000L

/**
 * Outcome of one capture. [sanityGatePassed] mirrors what was logged to Logcat (the relied-upon
 * channel per Components §2, since a facedown/pocketed phone can't show a toast). [routeIsBuiltinSpeaker]
 * being false, or a non-zero [xrunCount]/[droppedFrameCount], each mark the capture as contaminated
 * rather than silently feeding it into analysis.
 */
data class CaptureResult(
    val condition: Condition,
    val wavFile: File,
    val jsonFile: File,
    val capturedSampleCount: Int,
    val rms: Double,
    val sanityGatePassed: Boolean,
    val xrunCount: Int,
    val droppedFrameCount: Long,
    val sampleRate: Int,
    val outputRoute: String,
    val routeIsBuiltinSpeaker: Boolean,
)

/** Thrown when a capture cannot even start (stream open/start failed); a run that starts but is */
/** contaminated (XRuns, wrong route) still returns a [CaptureResult] with those flags set. */
class CaptureException(message: String) : Exception(message)

/**
 * Kotlin orchestration around [NativeBridge] (test2-step2-plan.md Stage 2 step 2): pins the media
 * volume, resolves the built-in speaker/mic route to force, drives the native full-duplex capture,
 * then does the WAV/JSON/RMS work Kotlin-side by reusing [writeWav]/[ConditionMetadata]/[rms] rather
 * than duplicating it in C++.
 *
 * NOT YET RUN ON A PHYSICAL DEVICE. This compiles and links, but every acoustic assumption below
 * (that the streams open in LowLatency/Exclusive, that the speaker route holds, that bleed clears
 * the sanity floor) is unverified until Tier 2/3 run on hardware -- no device has been connected to
 * this repo. See test2-step2-plan.md "Next steps" items 2-4.
 */
class CaptureEngine(private val context: Context) {

    private val audioManager: AudioManager =
        context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    /**
     * The device's native output sample rate (Components §1 / CLAUDE.md: query it, don't hardcode
     * 44.1/48k). Falls back to 48000 if the property is missing.
     */
    fun nativeOutputSampleRate(): Int {
        val prop = audioManager.getProperty(AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE)
        return prop?.toIntOrNull() ?: 48000
    }

    /**
     * Pins STREAM_MUSIC to its maximum index (Components §2: so `setVolume`/gain is reproducible in
     * absolute terms, not relative to a drifting slider) and returns the index it set.
     */
    fun pinMediaVolumeToMax(): Int {
        val maxIndex = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, maxIndex, 0)
        Log.i(TAG, "pinned STREAM_MUSIC volume to index $maxIndex")
        return maxIndex
    }

    /** Loads and decodes the bundled reference track asset into 16-bit PCM. */
    fun loadReferenceTrack(assetName: String = REFERENCE_TRACK_ASSET) =
        context.assets.open(assetName).use { readWav(it.readBytes()) }

    /**
     * Runs one full capture for [condition], writing `{conditionId}_{timestamp}.wav` and a matching
     * `.json` sidecar into [outputDir] (keyed on the timestamp so a retry never overwrites a prior
     * attempt, per Components §2). Throws [CaptureException] if the streams fail to open/start.
     *
     * [reference] defaults to the bundled asset; the Tier-2 instrumented tests inject a short
     * synthetic buffer so a capture completes in ~1s instead of the asset's 15s, which is what makes
     * the back-to-back-runs leak test tractable. Production callers pass nothing.
     */
    fun runCapture(
        condition: Condition,
        outputDir: File,
        reference: com.overdub.harness.wav.WavAudio = loadReferenceTrack(),
    ): CaptureResult {
        outputDir.mkdirs()

        val sampleRate = nativeOutputSampleRate()
        val streamVolumeIndex = pinMediaVolumeToMax()

        if (reference.format.sampleRate != sampleRate) {
            // Components §1: a rate mismatch confounds the bleed data via HAL resampling. Warn loudly
            // rather than silently resample -- the fix is to regenerate the reference at the native rate.
            Log.w(
                TAG,
                "reference track rate ${reference.format.sampleRate}Hz != device native ${sampleRate}Hz " +
                    "-- regenerate the reference at the native rate before trusting a real sweep",
            )
        }

        val speakerId = builtinDeviceId(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER, output = true)
        val micId = builtinDeviceId(AudioDeviceInfo.TYPE_BUILTIN_MIC, output = false)

        val gain = condition.volume.gainFraction.toFloat()

        val openResult = NativeBridge.nativeOpen(
            sampleRate,
            reference.format.channelCount,
            NativeBridge.INPUT_PRESET_VOICE_RECOGNITION,
            speakerId,
            micId,
        )
        if (openResult != NativeBridge.RESULT_OK) {
            throw CaptureException("nativeOpen failed with oboe::Result $openResult")
        }

        try {
            NativeBridge.nativeSetPlayback(reference.samples, gain)
            val startResult = NativeBridge.nativeStart()
            if (startResult != NativeBridge.RESULT_OK) {
                throw CaptureException("nativeStart failed with oboe::Result $startResult")
            }

            awaitPlaybackComplete(reference)
            Thread.sleep(CAPTURE_TAIL_MS)
            NativeBridge.nativeStop()

            val captured = NativeBridge.nativeGetCapturedSamples()
            val xrun = NativeBridge.nativeGetXRunCount()
            val dropped = NativeBridge.nativeGetDroppedFrameCount()
            val actualRate = NativeBridge.nativeGetActualSampleRate().takeIf { it > 0 } ?: sampleRate
            val outputDeviceId = NativeBridge.nativeGetOutputDeviceId()

            val (routeLabel, isSpeaker) = resolveOutputRoute(outputDeviceId)
            if (!isSpeaker) {
                Log.w(TAG, "output route is '$routeLabel', not the built-in speaker -- capture may be invalid")
            }
            if (xrun > 0) Log.w(TAG, "XRun count $xrun > 0 -- this capture is contaminated")
            if (dropped > 0) Log.w(TAG, "dropped $dropped captured samples (ring overflow)")

            val rmsValue = rms(captured)
            val sanityPassed = rmsValue > RMS_SANITY_FLOOR
            // Logcat is the relied-upon sanity channel (works regardless of phone orientation).
            if (sanityPassed) {
                Log.i(TAG, "SANITY PASS ${condition.conditionId}: rms=%.1f samples=%d".format(rmsValue, captured.size))
            } else {
                Log.w(TAG, "SANITY FAIL ${condition.conditionId}: rms=%.1f below floor $RMS_SANITY_FLOOR (bleed may not have reached the mic)".format(rmsValue))
            }

            val timestamp = System.currentTimeMillis()
            val baseName = "${condition.conditionId}_$timestamp"
            val wavFile = File(outputDir, "$baseName.wav")
            val jsonFile = File(outputDir, "$baseName.json")

            wavFile.writeBytes(writeWav(captured, WavFormat(actualRate, 16, reference.format.channelCount)))

            val metadata = ConditionMetadata(
                conditionId = condition.conditionId,
                playbackVolume = condition.volume.gainFraction,
                distanceCm = condition.distance.approxCm,
                orientation = condition.orientation.label,
                obstruction = condition.obstruction.label,
                outputRoute = routeLabel,
                inputPreset = "voice_recognition",
                sampleRate = actualRate,
                xrunCount = xrun,
                deviceModel = "${Build.MANUFACTURER} ${Build.MODEL}",
                streamVolumeIndex = streamVolumeIndex,
                timestamp = timestamp,
            )
            jsonFile.writeText(metadata.toJson())

            return CaptureResult(
                condition = condition,
                wavFile = wavFile,
                jsonFile = jsonFile,
                capturedSampleCount = captured.size,
                rms = rmsValue,
                sanityGatePassed = sanityPassed,
                xrunCount = xrun,
                droppedFrameCount = dropped,
                sampleRate = actualRate,
                outputRoute = routeLabel,
                routeIsBuiltinSpeaker = isSpeaker,
            )
        } finally {
            NativeBridge.nativeClose()
        }
    }

    private fun awaitPlaybackComplete(reference: com.overdub.harness.wav.WavAudio) {
        val frames = reference.samples.size / reference.format.channelCount
        val durationMs = frames * 1000L / reference.format.sampleRate
        val deadline = System.currentTimeMillis() + durationMs + PLAYBACK_TIMEOUT_MARGIN_MS
        while (!NativeBridge.nativeIsPlaybackComplete()) {
            if (System.currentTimeMillis() > deadline) {
                Log.w(TAG, "playback did not complete within ${durationMs + PLAYBACK_TIMEOUT_MARGIN_MS}ms -- stopping anyway")
                return
            }
            Thread.sleep(20)
        }
    }

    /** Finds the device id of the built-in speaker/mic to force the route, or -1 if not found. */
    private fun builtinDeviceId(type: Int, output: Boolean): Int {
        val flag = if (output) AudioManager.GET_DEVICES_OUTPUTS else AudioManager.GET_DEVICES_INPUTS
        return audioManager.getDevices(flag).firstOrNull { it.type == type }?.id ?: -1
    }

    /** Resolves the actual output device id into a label + whether it's the built-in speaker. */
    private fun resolveOutputRoute(deviceId: Int): Pair<String, Boolean> {
        val device = audioManager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            .firstOrNull { it.id == deviceId }
            ?: return ("unknown(id=$deviceId)" to false)
        val isSpeaker = device.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
        return (audioDeviceTypeLabel(device.type) to isSpeaker)
    }

    private fun audioDeviceTypeLabel(type: Int): String = when (type) {
        AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "builtin_speaker"
        AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> "builtin_earpiece"
        AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wired_headset"
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "wired_headphones"
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> "bluetooth_a2dp"
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bluetooth_sco"
        AudioDeviceInfo.TYPE_USB_HEADSET -> "usb_headset"
        AudioDeviceInfo.TYPE_USB_DEVICE -> "usb_device"
        else -> "type_$type"
    }
}
