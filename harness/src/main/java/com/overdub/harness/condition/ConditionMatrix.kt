package com.overdub.harness.condition

/**
 * The fixed 3x3x2x2 condition matrix from test2-step2-plan.md Components §3. Values and the
 * baseline cell (conversational volume, arm's length, face-up, unobstructed) are fixed there,
 * not chosen here.
 */
enum class Volume(val label: String, val gainFraction: Double, val isBaseline: Boolean) {
    QUIET("quiet", 0.2, false),
    CONVERSATIONAL("conversational", 0.6, true),
    LOUD("loud", 1.0, false),
}

enum class Distance(val label: String, val approxCm: Int, val isBaseline: Boolean) {
    NEAR("near", 15, false),
    ARMS_LENGTH("armslength", 50, true),
    FAR("far", 200, false),
}

enum class Orientation(val label: String, val isBaseline: Boolean) {
    FACE_UP("faceup", true),
    FACE_DOWN("facedown", false),
}

enum class Obstruction(val label: String, val isBaseline: Boolean) {
    NONE("none", true),
    POCKETED("pocketed", false),
}

data class Condition(
    val volume: Volume,
    val distance: Distance,
    val orientation: Orientation,
    val obstruction: Obstruction,
) {
    val conditionId: String
        get() = "${volume.label}_${distance.label}_${orientation.label}_${obstruction.label}"

    val isBaseline: Boolean
        get() = volume.isBaseline && distance.isBaseline && orientation.isBaseline && obstruction.isBaseline
}

/** The single baseline realistic condition referenced throughout test2-step2-plan.md. */
val BASELINE_CONDITION = Condition(Volume.CONVERSATIONAL, Distance.ARMS_LENGTH, Orientation.FACE_UP, Obstruction.NONE)

/** All 3 x 3 x 2 x 2 = 36 combinations, each appearing exactly once. */
fun generateConditionMatrix(): List<Condition> =
    Volume.entries.flatMap { volume ->
        Distance.entries.flatMap { distance ->
            Orientation.entries.flatMap { orientation ->
                Obstruction.entries.map { obstruction ->
                    Condition(volume, distance, orientation, obstruction)
                }
            }
        }
    }
