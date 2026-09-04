package com.football.app.report

/** The 9 report tabs, in display order (frontend/DESIGN.md). Ordinal
 * order also drives AnimatedContent's slide direction in ReportScreen --
 * moving to a later tab slides content in from the right, matching
 * apple-design's spatial-consistency rule. */
enum class ReportTab(
    val title: String,
) {
    OVERVIEW("Overview"),
    LINEUPS("Lineups"),
    PERFORMANCE("Performance"),
    DISCIPLINE("Discipline"),
    PROFILE("Profile"),
    STANDINGS("Standings"),
    CONTEXT("Context"),
    FORM("Form"),
    SQUAD("Squad"),
}
