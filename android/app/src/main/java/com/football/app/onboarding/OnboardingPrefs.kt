package com.football.app.onboarding

import android.content.Context

/**
 * Plain SharedPreferences, not DataStore -- a single boolean flag with
 * no concurrent-write concerns doesn't need DataStore's async/Flow
 * machinery or a new Gradle dependency.
 */
class OnboardingPrefs(
    context: Context,
) {
    private val prefs = context.getSharedPreferences("onboarding", Context.MODE_PRIVATE)

    var hasSeenOnboarding: Boolean
        get() = prefs.getBoolean(KEY_SEEN, false)
        set(value) = prefs.edit().putBoolean(KEY_SEEN, value).apply()

    private companion object {
        const val KEY_SEEN = "has_seen_onboarding"
    }
}
