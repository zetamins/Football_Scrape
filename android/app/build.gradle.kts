import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.chaquopy)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.kover)
}

// Loaded from keystore.properties (git-ignored, see .gitignore and
// keystore.properties.example) rather than hardcoded here -- this file
// itself IS committed, so the real store/key passwords must never be
// literals in it. Optional on purpose: `./gradlew assembleDebug` and
// every dev workflow that doesn't touch the release build type must
// keep working on a machine that has never had a release keystore
// configured (e.g. CI, or a fresh clone) -- only assembleRelease/
// bundleRelease actually need signingConfigs["release"] to exist.
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        keystorePropertiesFile.inputStream().use { load(it) }
    }
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
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            // Chaquopy needs at least one target ABI selected explicitly;
            // matches the emulator's system image (android-34/google_apis,
            // x86_64) so the debug build actually runs on the one device
            // available to test against here, plus arm64-v8a for real
            // devices. AGP's `splits.abi` mechanism (which would produce
            // smaller, single-ABI release APKs) is NOT usable together
            // with Chaquopy: Chaquopy requires ndk.abiFilters set
            // explicitly, but AGP rejects splits.abi being enabled at
            // all whenever ndk.abiFilters is non-empty -- confirmed via
            // two different build failures trying both orderings. A
            // one-off single-ABI override (see the arm64-v8a-only build
            // used to produce a smaller APK for manual testing) is the
            // workaround, not a standing config change.
            abiFilters += listOf("x86_64", "arm64-v8a")
        }
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            // Verified live (not assumed safe): the WebView bridge --
            // the one thing in this app Chaquopy reaches via string-based
            // reflection rather than a normal compiled reference -- still
            // worked correctly against a real site with minification and
            // the proguard-rules.pro keep rule both applied.
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
            // Falls back to unsigned when keystore.properties is absent
            // (e.g. CI, a fresh clone) rather than failing the build --
            // an unsigned release APK still compiles/installs-with-
            // --allow-unsafe-installs locally for testing minification,
            // it just can't be uploaded to Play as-is.
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
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)

    // Compose UI -- BOM pins every androidx.compose.* artifact below to
    // one mutually-compatible set, so only the BOM itself carries a
    // version number.
    implementation(platform(libs.compose.bom))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.navigation.compose)

    // Report JSON -> Kotlin data classes (see data/model/).
    implementation(libs.kotlinx.serialization.json)

    // Bar/line charts (see frontend/DESIGN.md's Chart library section --
    // radar/segmented/stacked bars are hand-rolled Canvas composables
    // instead, Vico doesn't cover those forms).
    implementation(libs.vico.compose)
    implementation(libs.vico.compose.m3)

    // Instrumented tests for WebViewRenderer.kt run on-device (a real
    // WebView can't run in a plain JVM unit test) against local, static
    // HTML served from a WebViewClient override -- not live external
    // sites, so they're deterministic and don't depend on network
    // conditions or third-party site behavior the way the manual
    // android_test.py-driven runs do.
    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.ext.junit)

    // Local JVM unit tests for data/model/* -- pure Kotlin serialization
    // logic, no Android framework needed, so these run on the plain JVM
    // (testDebugUnitTest) rather than needing a device/emulator like the
    // androidTest ones above.
    testImplementation(libs.junit)
    // Robolectric: simulates the Android framework (Build.VERSION.SDK_INT,
    // Service lifecycle, NotificationManager) on the plain JVM -- needed
    // specifically to regression-test SearchQueueService's API-26 guard
    // (SearchQueueServiceTest) against a simulated API 24 device without
    // needing an actual old-API emulator image.
    testImplementation(libs.robolectric)
    // ApplicationProvider.getApplicationContext() -- SearchQueueServiceTest
    // needs a real Context to fetch the system NotificationManager.
    testImplementation(libs.androidx.test.core)
    // Dispatchers.setMain()/runTest -- HistoryViewModel and ReportViewModel
    // both launch viewModelScope.launch(Dispatchers.IO) coroutines, which
    // need Dispatchers.Main.immediate available; a plain JVM unit test has
    // no real Android main looper to provide it without this.
    testImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(libs.androidx.test.core)
    // Serves real local HTTP content to the WebView under test -- closer
    // to production behavior than data: URLs (genuine navigation/multi-
    // page redirects, real onPageStarted/onPageFinished/readyState
    // timing against actual HTTP responses).
    androidTestImplementation(libs.okhttp.mockwebserver)
}
