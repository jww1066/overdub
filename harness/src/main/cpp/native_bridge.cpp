// Minimal placeholder proving the Oboe/CMake/NDK wiring links correctly.
//
// The real full-duplex capture engine (Components §2 of test2-step2-plan.md:
// output/input stream setup, InputPreset::VoiceRecognition,
// setPreferredDevice() speaker/mic forcing, the lock-free ring buffer,
// playback-volume pinning, XRun logging, the on-device RMS sanity gate) is
// Stage 2 step 2, not this step — this file only exists to give CMake a
// buildable target that actually calls into Oboe, so a build failure here
// means the dependency wiring is broken rather than the (not yet written)
// engine.

#include <jni.h>
#include <oboe/Oboe.h>

extern "C" JNIEXPORT jstring JNICALL
Java_com_overdub_harness_NativeBridge_nativeCheckOboeLinked(JNIEnv *env, jobject /* this */) {
    const char *text = oboe::convertToText(oboe::Result::OK);
    return env->NewStringUTF(text);
}
