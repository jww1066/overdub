// JNI bridge between NativeBridge.kt and the C++ FullDuplexEngine (test2-step2-plan.md Stage 2
// step 2). The engine does the real-time-critical audio work (Oboe full-duplex, lock-free ring
// buffer, XRun counting); WAV/JSON/RMS stay on the Kotlin side (reusing WavWriter/ConditionMetadata/
// Rms) per the plan, so this file only marshals across the boundary.
//
// A single global engine instance is enough: the harness runs one capture at a time, driven
// sequentially from one Kotlin thread. All lifecycle calls below assume that single-threaded driver.

#include <jni.h>
#include <memory>
#include <vector>

#include <oboe/Oboe.h>

#include "native_engine.h"

namespace {
std::unique_ptr<overdub::FullDuplexEngine> gEngine;
}  // namespace

extern "C" {

// Retained from the Stage 2 step-1 linkage placeholder: proves Oboe is actually callable, used by
// the smoke test rather than the capture path.
JNIEXPORT jstring JNICALL
Java_com_overdub_harness_NativeBridge_nativeCheckOboeLinked(JNIEnv *env, jobject /* this */) {
    const char *text = oboe::convertToText(oboe::Result::OK);
    return env->NewStringUTF(text);
}

JNIEXPORT jint JNICALL
Java_com_overdub_harness_NativeBridge_nativeOpen(JNIEnv * /* env */, jobject /* this */,
                                                 jint sampleRate, jint channelCount,
                                                 jint inputPreset, jint outputDeviceId,
                                                 jint inputDeviceId, jboolean captureFloat) {
    gEngine = std::make_unique<overdub::FullDuplexEngine>();
    return gEngine->open(sampleRate, channelCount, inputPreset, outputDeviceId, inputDeviceId,
                         captureFloat == JNI_TRUE);
}

JNIEXPORT void JNICALL
Java_com_overdub_harness_NativeBridge_nativeSetPlayback(JNIEnv *env, jobject /* this */,
                                                        jshortArray samples, jfloat gain) {
    if (!gEngine) return;
    jsize count = env->GetArrayLength(samples);
    jshort *elems = env->GetShortArrayElements(samples, nullptr);
    gEngine->setPlayback(reinterpret_cast<const int16_t *>(elems), static_cast<size_t>(count), gain);
    env->ReleaseShortArrayElements(samples, elems, JNI_ABORT);
}

JNIEXPORT jint JNICALL
Java_com_overdub_harness_NativeBridge_nativeStart(JNIEnv * /* env */, jobject /* this */) {
    if (!gEngine) return static_cast<jint>(oboe::Result::ErrorClosed);
    return gEngine->start();
}

JNIEXPORT void JNICALL
Java_com_overdub_harness_NativeBridge_nativeStop(JNIEnv * /* env */, jobject /* this */) {
    if (gEngine) gEngine->stop();
}

JNIEXPORT void JNICALL
Java_com_overdub_harness_NativeBridge_nativeClose(JNIEnv * /* env */, jobject /* this */) {
    if (gEngine) {
        gEngine->close();
        gEngine.reset();
    }
}

JNIEXPORT jboolean JNICALL
Java_com_overdub_harness_NativeBridge_nativeIsPlaybackComplete(JNIEnv * /* env */,
                                                               jobject /* this */) {
    return (gEngine && gEngine->isPlaybackComplete()) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jshortArray JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetCapturedSamples(JNIEnv *env, jobject /* this */) {
    if (!gEngine) return env->NewShortArray(0);
    size_t count = gEngine->capturedSampleCount();
    jshortArray result = env->NewShortArray(static_cast<jsize>(count));
    if (result == nullptr || count == 0) return result;
    std::vector<int16_t> buffer(count);
    size_t copied = gEngine->copyCapturedSamples(buffer.data(), count);
    env->SetShortArrayRegion(result, 0, static_cast<jsize>(copied),
                             reinterpret_cast<const jshort *>(buffer.data()));
    return result;
}

JNIEXPORT jfloatArray JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetCapturedFloatSamples(JNIEnv *env,
                                                                    jobject /* this */) {
    if (!gEngine) return env->NewFloatArray(0);
    size_t count = gEngine->capturedSampleCount();
    jfloatArray result = env->NewFloatArray(static_cast<jsize>(count));
    if (result == nullptr || count == 0) return result;
    std::vector<float> buffer(count);
    size_t copied = gEngine->copyCapturedSamplesFloat(buffer.data(), count);
    env->SetFloatArrayRegion(result, 0, static_cast<jsize>(copied), buffer.data());
    return result;
}

JNIEXPORT jint JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetXRunCount(JNIEnv * /* env */, jobject /* this */) {
    return gEngine ? gEngine->xRunCount() : -1;
}

JNIEXPORT jlong JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetDroppedFrameCount(JNIEnv * /* env */,
                                                                 jobject /* this */) {
    return gEngine ? static_cast<jlong>(gEngine->droppedFrameCount()) : 0;
}

JNIEXPORT jint JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetOutputDeviceId(JNIEnv * /* env */,
                                                              jobject /* this */) {
    return gEngine ? gEngine->outputDeviceId() : -1;
}

JNIEXPORT jint JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetInputDeviceId(JNIEnv * /* env */,
                                                             jobject /* this */) {
    return gEngine ? gEngine->inputDeviceId() : -1;
}

JNIEXPORT jint JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetActualSampleRate(JNIEnv * /* env */,
                                                                jobject /* this */) {
    return gEngine ? gEngine->actualSampleRate() : 0;
}

// --- Hardware stream timestamps (test2-step2-plan.md item 10) ---

JNIEXPORT jboolean JNICALL
Java_com_overdub_harness_NativeBridge_nativeHasStreamTimestamps(JNIEnv * /* env */,
                                                                jobject /* this */) {
    return (gEngine && gEngine->hasStreamTimestamps()) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jlong JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetOutputTimestampFrames(JNIEnv * /* env */,
                                                                    jobject /* this */) {
    return gEngine ? static_cast<jlong>(gEngine->outputTimestampFrames()) : -1;
}

JNIEXPORT jlong JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetOutputTimestampNanos(JNIEnv * /* env */,
                                                                   jobject /* this */) {
    return gEngine ? static_cast<jlong>(gEngine->outputTimestampNanos()) : -1;
}

JNIEXPORT jlong JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetInputTimestampFrames(JNIEnv * /* env */,
                                                                   jobject /* this */) {
    return gEngine ? static_cast<jlong>(gEngine->inputTimestampFrames()) : -1;
}

JNIEXPORT jlong JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetInputTimestampNanos(JNIEnv * /* env */,
                                                                  jobject /* this */) {
    return gEngine ? static_cast<jlong>(gEngine->inputTimestampNanos()) : -1;
}

// --- Multi-read timestamp series (test2-step2-plan.md item 13 (b)) ---

JNIEXPORT jlongArray JNICALL
Java_com_overdub_harness_NativeBridge_nativeGetTimestampSamples(JNIEnv *env, jobject /* this */) {
    if (!gEngine) return env->NewLongArray(0);
    auto flat = gEngine->timestampSamplesFlat();
    auto len = static_cast<jsize>(flat.size());
    jlongArray arr = env->NewLongArray(len);
    if (arr != nullptr && len > 0) {
        std::vector<jlong> jlongBuf(len);
        for (jsize i = 0; i < len; ++i) jlongBuf[i] = static_cast<jlong>(flat[i]);
        env->SetLongArrayRegion(arr, 0, len, jlongBuf.data());
    }
    return arr;
}

}  // extern "C"
