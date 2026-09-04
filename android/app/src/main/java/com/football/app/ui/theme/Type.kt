package com.football.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import com.football.app.R

// Barlow (SIL Open Font License, bundled as 5 static-weight res/font/
// files -- Barlow ships as separate weight files on Google Fonts, not a
// single variable font like the previous typeface, Manrope, did) -- a
// grotesque genuinely associated with sports broadcast/scoreboard
// graphics (ESPN-style stat displays), replacing Manrope per an
// explicit "a real stats font" request. Distinct from Manrope's softer
// geometric character: Barlow reads as data/scoreboard-native, which
// this app -- almost entirely numbers and comparisons -- specifically
// wants.
private val Barlow =
    FontFamily(
        Font(R.font.barlow_regular, weight = FontWeight.Normal),
        Font(R.font.barlow_medium, weight = FontWeight.Medium),
        Font(R.font.barlow_semibold, weight = FontWeight.SemiBold),
        Font(R.font.barlow_bold, weight = FontWeight.Bold),
        Font(R.font.barlow_extrabold, weight = FontWeight.ExtraBold),
    )

private val Base = Typography()

/** Every Material3 text role, same sizes/weights as the default Typography, only the font family swapped. */
val AppTypography =
    Typography(
        displayLarge = Base.displayLarge.copy(fontFamily = Barlow),
        displayMedium = Base.displayMedium.copy(fontFamily = Barlow),
        displaySmall = Base.displaySmall.copy(fontFamily = Barlow),
        headlineLarge = Base.headlineLarge.copy(fontFamily = Barlow),
        headlineMedium = Base.headlineMedium.copy(fontFamily = Barlow),
        headlineSmall = Base.headlineSmall.copy(fontFamily = Barlow),
        titleLarge = Base.titleLarge.copy(fontFamily = Barlow),
        titleMedium = Base.titleMedium.copy(fontFamily = Barlow),
        titleSmall = Base.titleSmall.copy(fontFamily = Barlow),
        bodyLarge = Base.bodyLarge.copy(fontFamily = Barlow),
        bodyMedium = Base.bodyMedium.copy(fontFamily = Barlow),
        bodySmall = Base.bodySmall.copy(fontFamily = Barlow),
        labelLarge = Base.labelLarge.copy(fontFamily = Barlow),
        labelMedium = Base.labelMedium.copy(fontFamily = Barlow),
        labelSmall = Base.labelSmall.copy(fontFamily = Barlow),
    )

/**
 * Every stat value, hero percentage, and stat-tile number should use
 * this, not body/label text styles -- tabular figures (fixed-width
 * digits, so a column of numbers aligns) per dataviz's own rule,
 * applied wherever a number appears rather than only in literal table
 * rows (see frontend/DESIGN.md's Premium direction section: precision
 * reads as expertise, and misaligned numbers read as carelessness).
 */
val StatNumberStyle =
    TextStyle(
        fontFamily = Barlow,
        fontFeatureSettings = "tnum",
        fontWeight = FontWeight.SemiBold,
    )
