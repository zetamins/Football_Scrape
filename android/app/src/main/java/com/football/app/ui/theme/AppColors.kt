package com.football.app.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * Home/away/status colors -- semantic slots Material 3's own ColorScheme
 * has no room for. Values are dataviz's own validated default palette
 * (categorical slots 1+2 for home/away, its fixed status palette) -- see
 * frontend/DESIGN.md's "Chart color system" section for the validation
 * rationale; nothing here is invented. Kept as a separate extension
 * rather than repurposing ColorScheme.primary/secondary because those
 * carry app-chrome meaning (see Theme.kt's brand accent), and reusing
 * them for "which team" would make chrome and data collide visually.
 */
data class AppColors(
    val homeSeries: Color,
    val awaySeries: Color,
    val statusGood: Color,
    val statusWarning: Color,
    val statusCritical: Color,
    // "Draw"/neutral segments (e.g. the prediction hero's draw-%
    // slice) -- dataviz's own baseline/axis token, not a categorical or
    // status color, since a draw isn't "team identity" or "good/bad".
    val neutral: Color,
    // Brand accent, not chart-categorical -- used for icons/badges/active
    // indicators/live-status chips (the reference sports-app aesthetic's
    // vibrant green), never for team identity or chart series. Validated
    // for contrast against its own theme's surface (dataviz's method,
    // scripts/validate_palette.js), not eyeballed -- see the commit that
    // introduced this for the exact contrast numbers checked.
    val brandBright: Color,
    // Squad value's Attack/Midfield/Defense/GK breakdown -- a distinct
    // categorical dimension from home/away (composition of one team's
    // value, not "which side"), so it uses slots 3/4/5/7 of dataviz's
    // palette (aqua/yellow/magenta/violet), never slots 1/2 (blue/orange,
    // already meaning home/away everywhere else in this app). Fixed
    // order, always Attack-Midfield-Defense-GK, never reassigned per
    // team. Validated (scripts/validate_palette.js): dark passes all
    // checks against #0F1A12; light gets a contrast WARN against its
    // surface, accepted because SquadValueSection always pairs each
    // segment with a direct text label, satisfying the "legal only with
    // secondary encoding" condition the WARN band requires.
    val squadCategorical: List<Color>,
)

val LightAppColors =
    AppColors(
        homeSeries = Color(0xFF2A78D6),
        awaySeries = Color(0xFFEB6834),
        statusGood = Color(0xFF0CA30C),
        statusWarning = Color(0xFFFAB219),
        statusCritical = Color(0xFFD03B3B),
        neutral = Color(0xFFC3C2B7),
        brandBright = Color(0xFF3E8A24),
        squadCategorical = listOf(Color(0xFF1BAF7A), Color(0xFFEDA100), Color(0xFFE87BA4), Color(0xFF4A3AA7)),
    )

val DarkAppColors =
    AppColors(
        homeSeries = Color(0xFF3987E5),
        awaySeries = Color(0xFFD95926),
        // Status colors are fixed, never themed (dataviz's own rule) --
        // same hex in both modes.
        statusGood = Color(0xFF0CA30C),
        statusWarning = Color(0xFFFAB219),
        statusCritical = Color(0xFFD03B3B),
        neutral = Color(0xFF383835),
        brandBright = Color(0xFF8FD13F),
        squadCategorical = listOf(Color(0xFF199E70), Color(0xFFC98500), Color(0xFFD55181), Color(0xFF9085E9)),
    )

val LocalAppColors = staticCompositionLocalOf { LightAppColors }

/** Usage: AppTheme.colors.homeSeries */
object AppTheme {
    val colors: AppColors
        @Composable get() = LocalAppColors.current
}
