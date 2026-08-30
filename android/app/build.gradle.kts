plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.football.app"
    compileSdk = 34

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
            isMinifyEnabled = false
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

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")

    // Instrumented tests for WebViewRenderer.kt run on-device (a real
    // WebView can't run in a plain JVM unit test) against local, static
    // HTML served from a WebViewClient override -- not live external
    // sites, so they're deterministic and don't depend on network
    // conditions or third-party site behavior the way the manual
    // android_test.py-driven runs do.
    androidTestImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:rules:1.7.0")
    androidTestImplementation("androidx.test:core:1.7.0")
    // Serves real local HTTP content to the WebView under test -- closer
    // to production behavior than data: URLs (genuine navigation/multi-
    // page redirects, real onPageStarted/onPageFinished/readyState
    // timing against actual HTTP responses).
    androidTestImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
