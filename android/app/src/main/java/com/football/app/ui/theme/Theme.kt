package com.football.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color

// Brand/chrome accent -- violet, categorical slot 7 in dataviz's
// palette, deliberately unused by home/away/status so app chrome (active
// tab, primary buttons, selection) never collides visually with what a
// data color means (see frontend/DESIGN.md's Premium direction section).
private val BrandLight = Color(0xFF4A3AA7)
private val BrandDark = Color(0xFF9085E9)

// Dark-first (DESIGN.md's Premium direction): these background/surface
// tokens are dataviz's own dark chart chrome (page plane / chart
// surface), reused here so app chrome and chart surfaces read as one
// system rather than two separately-tuned palettes.
private val DarkColorScheme = darkColorScheme(
    primary = BrandDark,
    secondary = BrandDark,
    background = Color(0xFF0D0D0D),
    surface = Color(0xFF1A1A19),
    onBackground = Color(0xFFFFFFFF),
    onSurface = Color(0xFFFFFFFF),
)

private val LightColorScheme = lightColorScheme(
    primary = BrandLight,
    secondary = BrandLight,
    background = Color(0xFFF9F9F7),
    surface = Color(0xFFFCFCFB),
    onBackground = Color(0xFF0B0B0B),
    onSurface = Color(0xFF0B0B0B),
)

@Composable
fun FootballTheme(
    // Dark-first is the app's stated default (DESIGN.md), but this still
    // follows the system setting rather than hardcoding true -- Apple's
    // own "Agency" principle (apple-design skill) argues for respecting
    // a user's existing OS choice over silently overriding it. A
    // deliberate always-dark launch would be a product decision to make
    // explicitly, not a default to fall into.
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val appColors = if (darkTheme) DarkAppColors else LightAppColors
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    CompositionLocalProvider(LocalAppColors provides appColors) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = AppTypography,
            content = content,
        )
    }
}
