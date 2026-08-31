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
)

val LightAppColors = AppColors(
    homeSeries = Color(0xFF2A78D6),
    awaySeries = Color(0xFFEB6834),
    statusGood = Color(0xFF0CA30C),
    statusWarning = Color(0xFFFAB219),
    statusCritical = Color(0xFFD03B3B),
    neutral = Color(0xFFC3C2B7),
)

val DarkAppColors = AppColors(
    homeSeries = Color(0xFF3987E5),
    awaySeries = Color(0xFFD95926),
    // Status colors are fixed, never themed (dataviz's own rule) --
    // same hex in both modes.
    statusGood = Color(0xFF0CA30C),
    statusWarning = Color(0xFFFAB219),
    statusCritical = Color(0xFFD03B3B),
    neutral = Color(0xFF383835),
)

val LocalAppColors = staticCompositionLocalOf { LightAppColors }

/** Usage: AppTheme.colors.homeSeries */
object AppTheme {
    val colors: AppColors
        @Composable get() = LocalAppColors.current
}
