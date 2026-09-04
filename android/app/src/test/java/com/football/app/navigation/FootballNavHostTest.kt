package com.football.app.navigation

import android.content.Context
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import com.football.app.onboarding.OnboardingPrefs
import kotlinx.serialization.json.Json
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

/** Never navigates into a state that would click Search/Run queue --
 * same reasoning as SearchScreenTest (that path starts a real
 * foreground service requiring Chaquopy's native Python runtime,
 * unavailable in a plain JVM test). Onboarding <-> Search <-> History
 * navigation itself doesn't touch that and is covered here. */
@RunWith(RobolectricTestRunner::class)
class FootballNavHostTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `starts on Onboarding for a first launch`() {
        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Get started").assertExists()
    }

    @Test
    fun `starts on Search once onboarding has already been seen`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("DeepXI").assertExists()
    }

    @Test
    fun `get started navigates from Onboarding to Search and marks onboarding as seen`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Get started").performClick()
        composeTestRule.onNodeWithText("DeepXI").assertExists()
        assert(OnboardingPrefs(context).hasSeenOnboarding)
    }

    @Test
    fun `history icon on Search navigates to History`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Team name").assertExists()

        composeTestRule.onNodeWithContentDescription("History").performClick()
        composeTestRule.onNodeWithText("No searches yet.").assertExists()
    }

    /**
     * Reaches the REPORT destination via History -> tap a saved entry,
     * not via a live search -- the only path to REPORT that doesn't
     * require Chaquopy's native Python runtime (SearchScreen's own
     * Search/Run-queue buttons start a real foreground service that
     * needs it, an accepted, documented gap elsewhere in this suite).
     * HistoryViewModel.open()/ReportViewModel.loadFromHistory() are pure
     * I/O + JSON decode, so this exercises FootballNavHost's REPORT
     * composable() lambda (previously fully uncovered) for real.
     */
    @Test
    fun `tapping a saved entry in History navigates to Report`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        // Same historyDir FootballNavHost itself constructs
        // (Context.filesDir/history) -- seeding through it here matches
        // exactly what a real saved search would have written.
        val rawJson =
            checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
                "sample_full_report.json missing from test resources"
            }.bufferedReader().readText()
        val report = Json { ignoreUnknownKeys = true }.decodeFromString(ReportJson.serializer(), rawJson)
        val historyRepository = HistoryRepository(File(context.filesDir, "history"))
        historyRepository.save(report, rawJson)

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithContentDescription("History").performClick()
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Brentford vs Sunderland").performClick()
        // HistoryViewModel.open() dispatches onto the real
        // Dispatchers.IO (FootballNavHost doesn't expose a test seam to
        // swap it, unlike HistoryViewModelTest's own ioDispatcher param)
        // -- waitForIdle() alone doesn't wait for that background-thread
        // hop, so a plain assertExists() right after the click flaked
        // (confirmed live: failed with "could not find any node...
        // Overview" even though the entry click itself registered fine).
        // waitUntil polls (with waitForIdle between attempts) until the
        // async loadFromHistory()-driven recomposition lands.
        composeTestRule.waitUntil(timeoutMillis = 5_000) {
            composeTestRule.onAllNodesWithText("Overview").fetchSemanticsNodes().isNotEmpty()
        }

        // "Overview" is the default-selected report tab pill -- unlike
        // "Generated <date>" or the team-vs-team title (both of which
        // HistoryRow itself also renders, so asserting on them here
        // would pass even if the click never actually navigated away
        // from History; confirmed live this exact mistake initially
        // produced a false-positive-passing test with Kover still
        // showing FootballNavHost's REPORT composable() lambda fully
        // uncovered). "Overview" only exists on Report's own tab bar.
        composeTestRule.onNodeWithText("Overview").assertExists()

        // Report's own onBack (resetToIdle() + popBackStack()) --
        // previously unexercised, since no test reached Report from
        // History before this one. Returning to History (not Search)
        // confirms popBackStack() actually walked back one entry, not
        // to the graph's start destination.
        composeTestRule.onNodeWithContentDescription("Back").performClick()
        composeTestRule.onNodeWithText("Brentford vs Sunderland").assertExists()
    }
}
