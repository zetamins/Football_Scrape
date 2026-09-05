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
    // WrongStartDestinationType crashes lintAnalyzeDebug with a
    // NoClassDefFoundError inside androidx.navigation.lint's own
    // BaseWrongStartDestinationTypeDetector while visiting
    // FootballNavHost.kt -- confirmed this is pre-existing and unrelated
    // to any change in this repo (reproduces identically on a clean
    // `git stash`'d checkout with zero local modifications), and matches
    // the exact workaround lint's own crash message suggests. Not a
    // signal that FootballNavHost.kt's real navigation setup is wrong --
    // the detector never gets far enough to report anything before it
    // crashes.
    lint {
        disable += "WrongStartDestinationType"
        disable += "ComposableDestinationInComposeScope"
        disable += "ComposableNavGraphInComposeScope"
    }
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

    testOptions {
        unitTests {
            // Required for Robolectric-based Compose tests (Phase 4):
            // without this, Robolectric can't find the merged debug
            // manifest at all ("No manifest file found at
            // ./AndroidManifest.xml"), which is where ui-test-manifest's
            // injected ComponentActivity declaration lives --
            // createComposeRule() launches that activity internally via
            // ActivityScenarioRule, and without the merged manifest that
            // launch fails outright ("Unable to resolve activity for
            // Intent... cmp=.../androidx.activity.ComponentActivity"),
            // confirmed live via this exact failure before adding this.
            isIncludeAndroidResources = true
        }
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

// Excludes generated code and the Chaquopy/WebView-JS-execution
// category from the unit-test (koverXmlReportDebug) coverage report --
// not a blanket carve-out, and deliberately doesn't cover every
// remaining gap (see .progress/full_coverage_plan.md for what's left
// unexcluded and why, including Canvas draw lambdas -- explicitly NOT
// excluded here despite being the single largest remaining category:
// investigated a class-name-pattern exclusion for them and confirmed it
// doesn't work, because a Compose Canvas{} draw lambda compiles to a
// METHOD on the same already-mostly-tested outer class
// (e.g. `PitchDiagram_XO_JAsU$lambda$5$lambda$4` is a method of
// `PitchDiagramKt`, not a separate nested class), and Kover's `classes()`
// filter only excludes whole classes. Extracting the draw body into a
// separately-named function wouldn't help either -- confirmed earlier
// this session (captureToImage()-under-Robolectric timeout
// investigation) that the underlying issue is Robolectric never running
// the actual draw phase at all in a plain unit test, not a lambda-vs-
// function naming question, so renaming wouldn't change what gets
// measured).
//
// - Generated code: BuildConfig, ComposableSingletons$MainActivityKt
//   (compiler-generated Compose content holders tied to MainActivity's
//   own Chaquopy-bound onCreate()) -- nothing to test, same as
//   excluding R.java would be if Kover measured resource classes.
// - Chaquopy's native Python runtime: MainActivity.onCreate,
//   SearchQueueService.onCreate, PythonBridge.runReport, via the
//   @ExcludedFromCoverage annotation -- see that annotation's own doc
//   comment (coverage/ExcludedFromCoverage.kt) for the full,
//   evidence-based rationale per method. WebViewRenderer's own
//   JS-dependent methods carried this same annotation earlier in this
//   pass but no longer do -- Robolectric's ShadowWebView turned out to
//   support answering evaluateJavascript() calls directly, so
//   WebViewRendererTest.kt now drives them for real; see that
//   annotation's doc comment for the full story.
kover {
    reports {
        filters {
            excludes {
                annotatedBy("com.football.app.coverage.ExcludedFromCoverage")
                classes(
                    "com.football.app.BuildConfig",
                    "com.football.app.ComposableSingletons\$MainActivityKt",
                    "com.football.app.ComposableSingletons\$MainActivityKt\$lambda-1\$1",
                    "com.football.app.ComposableSingletons\$MainActivityKt\$lambda-2\$1",
                    // Same kotlinx.serialization codegen category as the
                    // data/model/ package exclusion below, but this one
                    // class lives in data/history/ alongside
                    // HistoryRepository (real logic, deliberately NOT
                    // excluded) -- a whole-package exclusion would have
                    // hidden HistoryRepository's own branches too, so this
                    // is a single-class exclusion instead. HistoryEntry's
                    // real behavior (id/team/opponent/generatedAt field
                    // mapping) is already covered by
                    // HistoryRepositoryTest's save-then-list round-trip.
                    "com.football.app.data.history.HistoryEntry",
                )
                // data/model/ is exclusively plain @Serializable data
                // classes -- zero hand-written functions anywhere in the
                // package (verified by grepping for `fun` across every
                // file there). Their real behavior (field/@SerialName
                // mapping) is already covered by direct decode tests
                // against real backend JSON fixtures, unaffected by this
                // exclusion -- it only stops kotlinx.serialization's
                // compiler-generated write$Self/deserialize methods (a
                // present/absent branch per optional field, ~50+ per
                // class) from counting toward Kover's branch-coverage
                // metric. That generated code isn't reachable via any
                // Kover config short of a whole-package exclusion (no
                // method-level filter exists, and the generated method
                // lives on the same class as the fields themselves, not
                // a separately excludable nested class) -- same
                // generated-code-boilerplate category as BuildConfig/
                // ComposableSingletons above, just discovered later.
                packages("com.football.app.data.model")
            }
        }
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
    // Compose UI tests (Phase 4) run via Robolectric on the plain JVM
    // (testDebugUnitTest), not as instrumented androidTest -- this
    // machine's emulator is memory-constrained and has previously needed
    // manual recovery to boot at all (see progress notes from the
    // SearchQueueService live-testing session), making it an unreliable
    // dependency for routine test runs. createComposeRule() (not
    // createAndroidComposeRule<T>()) works under Robolectric directly,
    // matching this project's existing Robolectric usage
    // (SearchQueueServiceTest) rather than introducing a second,
    // device-dependent test mechanism.
    testImplementation(platform(libs.compose.bom))
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(libs.androidx.test.core)
    // Serves real local HTTP content to the WebView under test -- closer
    // to production behavior than data: URLs (genuine navigation/multi-
    // page redirects, real onPageStarted/onPageFinished/readyState
    // timing against actual HTTP responses).
    androidTestImplementation(libs.okhttp.mockwebserver)
}
