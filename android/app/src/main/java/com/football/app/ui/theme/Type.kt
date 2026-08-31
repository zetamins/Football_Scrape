package com.football.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

// Default platform system font (apple-design's "default to platform font
// before a custom face, override only with a reason" -- Compose's
// default Typography() already ships this via FontFamily.Default, so no
// explicit font family override is set here).
val AppTypography = Typography()

/**
 * Every stat value, hero percentage, and stat-tile number should use
 * this, not body/label text styles -- tabular figures (fixed-width
 * digits, so a column of numbers aligns) per dataviz's own rule,
 * applied wherever a number appears rather than only in literal table
 * rows (see frontend/DESIGN.md's Premium direction section: precision
 * reads as expertise, and misaligned numbers read as carelessness).
 */
val StatNumberStyle = TextStyle(
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
