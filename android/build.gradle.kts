plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.chaquopy) apply false
    // Compose Compiler is a separate Gradle plugin as of Kotlin 2.0 (no
    // longer configured via composeOptions.kotlinCompilerExtensionVersion)
    // -- versioned identically to the Kotlin plugin above (see
    // gradle/libs.versions.toml's shared `kotlin` version ref), not
    // independently.
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kover) apply false
}
