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
# APIs -- no other reflection-based lookups into app code exist today.
# Chaquopy's own runtime classes (com.chaquo.python.*) ship their own
# consumer ProGuard rules and don't need duplicating here.
