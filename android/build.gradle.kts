plugins {
    id("com.android.application") version "8.13.2" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("com.chaquo.python") version "17.0.0" apply false
    // Compose Compiler is a separate Gradle plugin as of Kotlin 2.0 (no
    // longer configured via composeOptions.kotlinCompilerExtensionVersion)
    // -- versioned identically to the Kotlin plugin above, not
    // independently.
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.0.21" apply false
}
