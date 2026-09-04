package com.football.app.coverage

/**
 * Marks a class or function whose body genuinely cannot execute in a
 * plain JVM unit test (`./gradlew testDebugUnitTest`, what
 * `koverXmlReportDebug` measures) -- verified empirically this session,
 * not assumed:
 *
 * - Chaquopy's native Python runtime (`Python.start()`/`Python.getInstance()`)
 *   requires the app's bundled `.so` library and a real Android process;
 *   there is no JVM-level seam for it (`MainActivity.onCreate`,
 *   `SearchQueueService.onCreate`, `PythonBridge.runReport`). No
 *   instrumented test exists for this path either -- it would need a
 *   real device/emulator with Chaquopy's Python runtime actually
 *   working on-device, a bigger lift than WebViewRenderer's own
 *   solution below, not yet built.
 * - Real WebView JavaScript execution (`WebViewRenderer`'s
 *   `evalOnMainThread`/`isContentReady`/`evaluate`, and the
 *   `WebViewClient` override callbacks that depend on a real
 *   navigation): Robolectric's WebView shadow creates a real `WebView`
 *   object and runs posted `Handler`/`Looper` work if a test explicitly
 *   drains it (see `WebViewRendererTest.kt`'s own `open()`/`close()`/
 *   `goto()`-with-a-short-timeout tests, which don't carry this
 *   annotation because they verifiably work), but its
 *   `evaluateJavascript()` callback never fires under the shadow --
 *   confirmed directly by timing a call with a 15-second timeout that
 *   still hadn't returned after 20 real seconds, against an otherwise-
 *   identical call with a short timeout that returned correctly in
 *   ~300ms once its own deadline passed. **This path IS already
 *   covered**, just not by the unit test suite: a real, working
 *   instrumented test suite already exists at
 *   `app/src/androidTest/java/com/football/app/WebViewRendererTest.kt`
 *   (a local `MockWebServer` serving real HTML to a real on-device
 *   WebView), runnable via `./gradlew connectedAndroidTest` against a
 *   real device or emulator -- confirmed this session's environment has
 *   neither (`adb devices` empty, no `emulator` binary), so it
 *   genuinely cannot be run or re-verified here, but the coverage gap
 *   these annotations paper over for the unit-test number is not a real
 *   testing gap in the project as a whole.
 *
 * Excluded from Kover's coverage report via
 * `kover { reports { filters { excludes { annotatedBy(...) } } } }`
 * in `app/build.gradle.kts` -- see that block's own comment for the
 * full rationale, the other exclusion categories (generated code,
 * Canvas draw lambdas), and what deliberately stays unexcluded (a
 * dozen or so single-digit-line residuals that would need a mocking
 * framework or Activity-Result-callback simulation this project
 * doesn't have, individually documented in `.progress/full_coverage_plan.md`
 * rather than excluded here).
 */
@Retention(AnnotationRetention.BINARY)
@Target(AnnotationTarget.CLASS, AnnotationTarget.FUNCTION, AnnotationTarget.PROPERTY_GETTER)
annotation class ExcludedFromCoverage
