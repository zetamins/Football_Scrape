package com.football.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.football.app.R

// Manrope (SIL Open Font License, bundled as res/font/manrope_variable.ttf)
// -- a geometric sans with a distinct, modern character, replacing the
// platform default per an explicit request for an app-wide distinctive
// typeface (this project's prior default-platform-font stance was
// "override only with a reason"; a direct ask for one is that reason).
// One variable-font file, multiple Font() entries selecting different
// weights from it via FontVariation.Settings -- the standard Compose
// pattern for variable fonts, rather than bundling 6 separate static
// files.
private val Manrope = FontFamily(
    Font(R.font.manrope_variable, weight = FontWeight.Normal),
    Font(R.font.manrope_variable, weight = FontWeight.Medium),
    Font(R.font.manrope_variable, weight = FontWeight.SemiBold),
    Font(R.font.manrope_variable, weight = FontWeight.Bold),
    Font(R.font.manrope_variable, weight = FontWeight.ExtraBold),
)

private val Base = Typography()

/** Every Material3 text role, same sizes/weights as the default Typography, only the font family swapped. */
val AppTypography = Typography(
    displayLarge = Base.displayLarge.copy(fontFamily = Manrope),
    displayMedium = Base.displayMedium.copy(fontFamily = Manrope),
    displaySmall = Base.displaySmall.copy(fontFamily = Manrope),
    headlineLarge = Base.headlineLarge.copy(fontFamily = Manrope),
    headlineMedium = Base.headlineMedium.copy(fontFamily = Manrope),
    headlineSmall = Base.headlineSmall.copy(fontFamily = Manrope),
    titleLarge = Base.titleLarge.copy(fontFamily = Manrope),
    titleMedium = Base.titleMedium.copy(fontFamily = Manrope),
    titleSmall = Base.titleSmall.copy(fontFamily = Manrope),
    bodyLarge = Base.bodyLarge.copy(fontFamily = Manrope),
    bodyMedium = Base.bodyMedium.copy(fontFamily = Manrope),
    bodySmall = Base.bodySmall.copy(fontFamily = Manrope),
    labelLarge = Base.labelLarge.copy(fontFamily = Manrope),
    labelMedium = Base.labelMedium.copy(fontFamily = Manrope),
    labelSmall = Base.labelSmall.copy(fontFamily = Manrope),
)

/**
 * Every stat value, hero percentage, and stat-tile number should use
 * this, not body/label text styles -- tabular figures (fixed-width
 * digits, so a column of numbers aligns) per dataviz's own rule,
 * applied wherever a number appears rather than only in literal table
 * rows (see frontend/DESIGN.md's Premium direction section: precision
 * reads as expertise, and misaligned numbers read as carelessness).
 */
val StatNumberStyle = TextStyle(
    fontFamily = Manrope,
    fontFeatureSettings = "tnum",
    fontWeight = FontWeight.SemiBold,
)

/**
 * Large standalone figures (prediction hero %, big stat-tile numbers) --
 * negative tracking as size grows, per apple-design's size-specific
 * typography rule (large text reads too loose at zero tracking; a fixed
 * letter-spacing is wrong at some size).
 */
val HeroNumberStyle = StatNumberStyle.copy(
    fontSize = 40.sp,
    letterSpacing = (-0.02).em,
)
