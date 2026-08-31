package com.football.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

// Brand/chrome accent -- a jade green (active tab, primary buttons,
// selection), deliberately unused by home/away/status so app chrome
// never collides visually with what a data color means. Same hex in
// both themes (one consistent brand color, matching how most sports-app
// references treat their accent) -- validated at 4.52:1 white-text
// contrast (dataviz's method: scripts/validate_palette.js's underlying
// WCAG contrast check, run manually against #FFFFFF since this is a
// solid UI fill, not a chart categorical mark) so a white button label
// stays AA-legible on it regardless of theme.
private val Brand = Color(0xFF218838)

// Dark-first (DESIGN.md's Premium direction): a deep forest-green-black,
// not a neutral gray-black, so app chrome and the pitch-diagram/brand
// green read as one deliberate palette rather than a generic dark theme
// with a green accent bolted on. Validated against dataviz's method
// (scripts/validate_palette.js, --mode dark --surface "#0F1A12"): home/
// away series and status colors all pass contrast against this surface
// unchanged from their prior neutral-dark values.
private val DarkColorScheme = darkColorScheme(
    primary = Brand,
    onPrimary = Color.White,
    secondary = Brand,
    onSecondary = Color.White,
    background = Color(0xFF0F1A12),
    onBackground = Color(0xFFF4F7F2),
    surface = Color(0xFF17241A),
    onSurface = Color(0xFFF4F7F2),
    // Unset roles (surfaceVariant/outline/etc.) otherwise fall back to
    // Material3's own baseline-violet defaults, not this theme's green --
    // set explicitly so OutlinedTextField borders, muted labels, and
    // Card containers all read as one palette, not baseline M3 peeking
    // through around the parts this theme didn't override.
    surfaceVariant = Color(0xFF1E2E22),
    onSurfaceVariant = Color(0xFF8FA391),
    outline = Color(0xFF3A4F3E),
    outlineVariant = Color(0xFF2A3B2E),
)

private val LightColorScheme = lightColorScheme(
    primary = Brand,
    onPrimary = Color.White,
    secondary = Brand,
    onSecondary = Color.White,
    background = Color(0xFFF9F9F7),
    onBackground = Color(0xFF0B0B0B),
    surface = Color(0xFFFCFCFB),
    onSurface = Color(0xFF0B0B0B),
    surfaceVariant = Color(0xFFEFF1EC),
    onSurfaceVariant = Color(0xFF49524B),
    outline = Color(0xFFC7CDC5),
    outlineVariant = Color(0xFFDEE3DC),
)

// Rounder than Material3's defaults (medium=12dp/large=16dp) across the
// board -- the reference's whole visual language is heavily rounded
// (cards, pills, buttons); this is the one central override that lifts
// every Card/Button/Dialog toward that without touching each call site.
private val AppShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
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
            shapes = AppShapes,
        ) {
            // Without this, colorScheme.background never actually paints
            // anywhere -- every screen's root Column has no background
            // modifier of its own, so the Activity's plain AppCompat
            // DayNight window background (a generic gray, not this
            // theme's colors) was showing through underneath. Confirmed
            // live: dark mode rendered as flat #303030, not this theme's
            // #0F1A12, until this Surface was added.
            Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                content()
            }
        }
    }
}
