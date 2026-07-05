cmake_minimum_required(VERSION 3.22.1)
project("overdub_harness")

# Oboe is resolved via the prefab-packaged AAR (build.gradle.kts's
# `com.google.oboe:oboe` dependency + `buildFeatures.prefab = true`), not
# vendored source, per test2-step2-plan.md's Stage 2 step 1.
find_package(oboe REQUIRED CONFIG)

add_library(overdub_harness SHARED
    native_bridge.cpp
    native_engine.cpp)

target_link_libraries(overdub_harness
    oboe::oboe
    android
    log)
