package com.overdub.harness

/**
 * JNI entry point into `native_bridge.cpp`. Today this only proves the
 * Oboe/CMake/NDK wiring links correctly; the real full-duplex capture engine
 * is Stage 2 step 2 of test2-step2-plan.md, not this step.
 */
object NativeBridge {
    init {
        System.loadLibrary("overdub_harness")
    }

    external fun nativeCheckOboeLinked(): String
}
