package com.football.app.coverage

/**
 * Marks a class or function whose body genuinely cannot execute in a
 * plain JVM unit test (`./gradlew testDebugUnitTest`, what
 * `koverXmlReportDebug` measures) -- verified empirically this session,
 * not assumed. As of this pass, that's down to exactly one category:
 *
 * - Chaquopy's native Python runtime (`Python.start()`/`Python.getInstance()`)
 *   requires the app's bundled `.so` library and a real Android process;
 *   there is no JVM-level seam for it (`MainActivity.onCreate`,
 *   `SearchQueueService.onCreate`, `PythonBridge.runReport`). No
 *   instrumented test exists for this path -- it would need a real
 *   device/emulator with Chaquopy's Python runtime actually working
 *   on-device, not yet built.
 *
 * **WebView JavaScript execution turned out NOT to belong in this
 * category**, despite an earlier pass in this same session concluding
 * otherwise: `evaluateJavascript()`'s callback never fires *on its
 * own* under Robolectric's shadow, but `ShadowWebView` exposes
 * `getLastEvaluatedJavascriptCallback()`/`getLastEvaluatedJavascript()`,
 * letting a test intercept each call and answer it directly --
 * `WebViewRendererTest.kt` now drives `goto()`/`evaluate()`'s full
 * success and error paths for real this way, including simulating
 * `onPageStarted` by calling `webView.webViewClient.onPageStarted(...)`
 * directly. None of `WebViewRenderer`'s methods carry this annotation
 * any more as a result. The still-pre-existing, real instrumented suite
 * at `app/src/androidTest/java/com/football/app/WebViewRendererTest.kt`
 * (a local `MockWebServer` serving real HTML to a real on-device
 * WebView) remains the higher-fidelity check against actual Chromium
 * behavior -- this unit-test-level simulation validates
 * `WebViewRenderer`'s own control flow (readiness polling, challenge-
 * title detection, error propagation), not real JS engine behavior --
 * but it's no longer the only coverage this logic has.
 *
 * Excluded from Kover's coverage report via
 * `kover { reports { filters { excludes { annotatedBy(...) } } } }`
 * in `app/build.gradle.kts` -- see that block's own comment for the
 * full rationale, the other exclusion categories (generated code,
 * Canvas draw lambdas), and what deliberately stays unexcluded (a
 * handful of single-digit-line residuals that are either structurally
 * unreachable or would need a mocking framework this project doesn't
 * have, individually documented in `.progress/full_coverage_plan.md`
 * rather than excluded here).
 */
@Retention(AnnotationRetention.BINARY)
@Target(AnnotationTarget.CLASS, AnnotationTarget.FUNCTION, AnnotationTarget.PROPERTY_GETTER)
annotation class ExcludedFromCoverage
