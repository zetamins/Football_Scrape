package com.football.app.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.football.app.data.history.HistoryRepository
import com.football.app.history.HistoryScreen
import com.football.app.onboarding.OnboardingPrefs
import com.football.app.onboarding.OnboardingScreen
import com.football.app.report.HistoryViewModel
import com.football.app.report.ReportScreen
import com.football.app.report.ReportViewModel
import com.football.app.search.SearchScreen
import java.io.File

object Destinations {
    const val ONBOARDING = "onboarding"
    const val SEARCH = "search"
    const val REPORT = "report"
    const val HISTORY = "history"
}

@Composable
fun FootballNavHost(navController: NavHostController = rememberNavController()) {
    // historyDir is Context.filesDir/history, app-private -- no runtime
    // permission needed (distinct from the Download JSON button's SAF
    // flow, which writes to a user-chosen location outside the app's
    // own storage).
    val context = LocalContext.current
    val historyRepository = remember { HistoryRepository(File(context.filesDir, "history")) }
    val onboardingPrefs = remember { OnboardingPrefs(context) }

    // Shared across all three destinations, scoped to this NavHost's
    // default ViewModelStoreOwner (the hosting Activity) -- retrieved
    // once here, not re-created per screen. See frontend/DESIGN.md's
    // Screen/nav section for why this is nav-graph-scoped rather than
    // per-screen.
    //
    // Built via an explicit factory, not the default reflective one --
    // both ViewModels take constructor parameters (manual DI, see
    // DESIGN.md's DI decision), which the default no-arg-reflection-
    // based ViewModelProvider factory can't satisfy.
    val reportViewModel: ReportViewModel =
        viewModel(
            factory = viewModelFactory { initializer { ReportViewModel(historyRepository = historyRepository) } },
        )
    val historyViewModel: HistoryViewModel =
        viewModel(
            factory = viewModelFactory { initializer { HistoryViewModel(historyRepository) } },
        )

    val startDestination = if (onboardingPrefs.hasSeenOnboarding) Destinations.SEARCH else Destinations.ONBOARDING

    NavHost(navController = navController, startDestination = startDestination) {
        composable(Destinations.ONBOARDING) {
            OnboardingScreen(
                onGetStarted = {
                    onboardingPrefs.hasSeenOnboarding = true
                    navController.navigate(Destinations.SEARCH) { popUpTo(Destinations.ONBOARDING) { inclusive = true } }
                },
            )
        }
        composable(Destinations.SEARCH) {
            SearchScreen(
                viewModel = reportViewModel,
                onReportReady = { navController.navigate(Destinations.REPORT) },
                onHistoryClick = { navController.navigate(Destinations.HISTORY) },
            )
        }
        composable(Destinations.REPORT) {
            ReportScreen(
                viewModel = reportViewModel,
                onBack = {
                    reportViewModel.resetToIdle()
                    navController.popBackStack()
                },
                onHistoryClick = { navController.navigate(Destinations.HISTORY) },
            )
        }
        composable(Destinations.HISTORY) {
            HistoryScreen(
                historyViewModel = historyViewModel,
                reportViewModel = reportViewModel,
                onBack = { navController.popBackStack() },
                onReportReady = { navController.navigate(Destinations.REPORT) },
            )
        }
    }
}
