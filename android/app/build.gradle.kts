plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.football.app"
    // 35, not 34: androidx.core 1.15.0 (a transitive Compose dependency)
    // requires compiling against API 35+ (verified via a real
    // checkDebugAarMetadata failure, not assumed). targetSdk/minSdk
    // unchanged -- this only affects which compile-time APIs are
    // available, not runtime behavior or device compatibility.
    compileSdk = 35

    defaultConfig {
        applicationId = "com.football.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            // Chaquopy needs at least one target ABI selected explicitly;
            // matches the emulator's system image (android-34/google_apis,
            // x86_64) so the debug build actually runs on the one device
            // available to test against here.
            abiFilters += listOf("x86_64", "arm64-v8a")
        }
    }

    buildTypes {
        release {
            // Verified live (not assumed safe): the WebView bridge --
            // the one thing in this app Chaquopy reaches via string-based
            // reflection rather than a normal compiled reference -- still
            // worked correctly against a real site with minification and
            // the proguard-rules.pro keep rule both applied. Signing for
            // real distribution is not configured here; that's the
            // owner's own release keystore, not something to invent.
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // No signingConfig set here -- real distribution needs the
            // owner's own release keystore, not a fabricated or debug
            // one. Until one is configured, `./gradlew assembleRelease`
            // produces an unsigned APK that can't be installed directly.
        }
    }

    buildFeatures {
        // Generates BuildConfig.DEBUG -- WebViewRenderer.kt gates its
        // diagnostic logging behind it, off by default since AGP 8.
        buildConfig = true
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        // Matches this machine's installed python3.13 -- Chaquopy needs a
        // matching host ("buildPython") interpreter to resolve/install pip
        // packages during the build, and no 3.12 is installed here.
        version = "3.13"

        pip {
            // Chaquopy's own pip repository has pre-built Android wheels for
            // these; httpx itself and the rest of its dependency tree
            // (httpcore, h11, h2, hpack, hyperframe, certifi, idna, sniffio,
            // anyio) are all pure Python, so no native build is needed.
            install("httpx[http2]")
        }

        // The existing backend/ package (one source of truth -- not
        // copied) is the Python source root: backend/football/ is a real
        // package directly under it, and Chaquopy's default source dir
        // (app/src/main/python) is a symlink to it (see PY_SOURCE_LINK
        // note below / the actual symlink created alongside this file).
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")

    // Compose UI -- BOM pins every androidx.compose.* artifact below to
    // one mutually-compatible set, so only the BOM itself carries a
    // version number.
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.4")

    // Report JSON -> Kotlin data classes (see data/model/).
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // Bar/line charts (see frontend/DESIGN.md's Chart library section --
    // radar/segmented/stacked bars are hand-rolled Canvas composables
    // instead, Vico doesn't cover those forms).
    implementation("com.patrykandpatrick.vico:compose:2.0.0")
    implementation("com.patrykandpatrick.vico:compose-m3:2.0.0")

    // Instrumented tests for WebViewRenderer.kt run on-device (a real
    // WebView can't run in a plain JVM unit test) against local, static
    // HTML served from a WebViewClient override -- not live external
    // sites, so they're deterministic and don't depend on network
    // conditions or third-party site behavior the way the manual
    // android_test.py-driven runs do.
    androidTestImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")

    // Local JVM unit tests for data/model/* -- pure Kotlin serialization
    // logic, no Android framework needed, so these run on the plain JVM
    // (testDebugUnitTest) rather than needing a device/emulator like the
    // androidTest ones above.
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:rules:1.7.0")
    androidTestImplementation("androidx.test:core:1.7.0")
    // Serves real local HTTP content to the WebView under test -- closer
    // to production behavior than data: URLs (genuine navigation/multi-
    // page redirects, real onPageStarted/onPageFinished/readyState
    // timing against actual HTTP responses).
    androidTestImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
