# WebViewRenderer.kt is loaded by Chaquopy via string-based reflection
# (football/browser.py: jclass("com.football.app.WebViewRenderer")) --
# R8 has no static reference to follow for that lookup, so without an
# explicit keep rule, minification/shrinking can rename or strip the
# class or its methods with no compile-time warning, only a runtime
# failure the first time the Android WebView backend is actually used.
# Keep the whole class (fields/methods included) rather than trying to
# enumerate exactly what Python calls, since that surface can grow.
-keep class com.football.app.WebViewRenderer { *; }

# MainActivity is only reached via Chaquopy calling
# football.android_bridge.set_application_context(applicationContext) and
# football.android_test's functions calling back into normal Android
# APIs.
#
# ACTUAL ROOT CAUSE of every release-build crash/error diagnosed this
# session (the two "TypeError" callable failures below, AND a
# release-only native SIGSEGV in libpython3.13.so's PyObject_GC_Del
# during Python.startNative -- confirmed via a debug-vs-release
# comparison on the identical emulator: debug launched clean every
# time, release crashed 100% of the time): Chaquopy's Gradle plugin
# auto-generates its OWN required consumer proguard file at
# app/build/python/proguard-rules.pro (containing, notably, `-keep class
# com.chaquo.python.** { * ; }` and `-keep class kotlin.jvm.functions.**
# { * ; }` -- exactly the SAM/functional-interface machinery this app's
# own PythonBridge rules below also need). That generated file's
# presence at minification time depends on Gradle task ordering that,
# at least once this session (after `./gradlew clean assembleRelease`),
# did NOT hold -- R8 logged "Supplied proguard configuration does not
# exist: .../build/python/proguard-rules.pro" and silently proceeded
# WITHOUT any of Chaquopy's own protections, corrupting enough of
# Chaquopy's runtime class layout to crash Python's native init itself,
# not just the app-level PythonBridge interfaces.
#
# Fix: don't depend on that generated file's timing at all -- the same
# rules are duplicated here, in this project's own tracked
# proguard-rules.pro, which proguardFiles() in build.gradle.kts loads
# unconditionally on every build regardless of Chaquopy's task graph.
-keep class com.chaquo.python.** { *; }
-keep class kotlin.jvm.functions.** { *; }
-keep class kotlin.jvm.internal.FunctionBase { *; }
-keep class kotlin.reflect.KAnnotatedElement { *; }
-dontwarn org.jetbrains.annotations.NotNull

# PythonBridge's three `fun interface`s (ProgressListener,
# SourceProgressListener, FailureListener -- all share the identical
# erased (String) -> Unit shape, so the class-merging failure described
# below applies to FailureListener exactly as to the first two) cross the Kotlin<->Python boundary the same
# way WebViewRenderer does, but via a DIFFERENT mechanism than string-
# reflection: football/android_report.py's run_report() calls the Kotlin
# lambda objects passed here as plain Python callables
# (on_progress(message)), which only works because Chaquopy's runtime
# reflects on the object at call time to confirm it implements a
# single-abstract-method ("functional") interface -- see this file's own
# docstring, and Chaquopy's docs on calling Java objects as functions
# ("If a Java object implements a functional interface, then it can be
# called like a function using () syntax"). R8 renaming or stripping
# either the interface's abstract method or the SAM-conversion-generated
# implementing class breaks that detection -- with no compile-time
# warning, only a release-build-only runtime failure.
#
# These -keep rules went through 2 confirmed-live-broken iterations
# before this one:
#   1. No rules at all -> "...is not callable because it implements no
#      functional interfaces" (R8 stripped/renamed the interface or its
#      SAM method).
#   2. -keep on the two interfaces + `-keepclassmembers class *
#      implements ...` on their implementations -> DIFFERENT failure:
#      "TypeError: b implements multiple functional interfaces (...
#      ProgressListener, ... SourceProgressListener): use cast() to
#      select one". Root cause: `-keepclassmembers` only protects a
#      class's MEMBERS from removal/renaming -- it does NOT stop R8 from
#      merging the class itself with another structurally-identical one.
#      ProgressListener.onMessage(String) and SourceProgressListener.
#      onSourceStatus(String) have identical erased signatures (one
#      String param, Unit return), so R8's class-merging optimization
#      merged their two separate SAM-lambda implementation classes into
#      one shared class implementing BOTH interfaces -- which Chaquopy's
#      runtime then can't disambiguate. A follow-up `-optimizations
#      !class/merging/*` addition did NOT fix it either (R8's own
#      "-optimizations" support doesn't reliably map onto legacy
#      ProGuard's optimization-pass names -- unlike `-keep`, which both
#      tools implement identically and unconditionally).
#
# The fix: plain `-keep class * implements ... { *; }` (not
# -keepclassmembers) on the IMPLEMENTING classes. `-keep` is the
# strongest directive in both ProGuard and R8 -- it blocks shrinking,
# optimizing (which is what class-merging is), AND obfuscating the
# matched class as a whole, not just its members.
-keep interface com.football.app.data.bridge.PythonBridge$ProgressListener { *; }
-keep interface com.football.app.data.bridge.PythonBridge$SourceProgressListener { *; }
-keep class * implements com.football.app.data.bridge.PythonBridge$ProgressListener { *; }
-keep class * implements com.football.app.data.bridge.PythonBridge$SourceProgressListener { *; }
-keep interface com.football.app.data.bridge.PythonBridge$FailureListener { *; }
-keep class * implements com.football.app.data.bridge.PythonBridge$FailureListener { *; }
-keepattributes InnerClasses, EnclosingMethod, Signature
