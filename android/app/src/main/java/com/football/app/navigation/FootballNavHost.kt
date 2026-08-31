package com.football.app.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.football.app.report.ReportScreen
import com.football.app.report.ReportViewModel
import com.football.app.search.SearchScreen

object Destinations {
    const val SEARCH = "search"
    const val REPORT = "report"
}

@Composable
fun FootballNavHost(navController: NavHostController = rememberNavController()) {
    // Shared across both destinations, scoped to this NavHost's default
    // ViewModelStoreOwner (the hosting Activity) -- retrieved once here,
    // not re-created per screen. See frontend/DESIGN.md's Screen/nav
    // section for why this is nav-graph-scoped rather than per-screen.
    //
    // Built via an explicit factory, not the default reflective one --
    // ReportViewModel's constructor takes a ReportRepository parameter
    // (manual DI, see DESIGN.md's DI decision), which the default
    // no-arg-reflection-based ViewModelProvider factory can't satisfy.
    val reportViewModel: ReportViewModel = viewModel(
        factory = viewModelFactory { initializer { ReportViewModel() } },
    )

    NavHost(navController = navController, startDestination = Destinations.SEARCH) {
        composable(Destinations.SEARCH) {
            SearchScreen(
                viewModel = reportViewModel,
                onReportReady = { navController.navigate(Destinations.REPORT) },
            )
        }
        composable(Destinations.REPORT) {
            ReportScreen(viewModel = reportViewModel)
        }
    }
}
