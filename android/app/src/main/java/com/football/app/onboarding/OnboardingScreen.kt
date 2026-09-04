package com.football.app.onboarding

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.football.app.components.Logo
import com.football.app.ui.theme.AppTheme

/**
 * First-launch-only splash (FootballNavHost checks OnboardingPrefs and
 * skips straight to Search on every later launch -- see that file). Not
 * a literal clone of the reference mockup's onboarding screen: that one
 * shows a real athlete photo and copy about "watching matches" and
 * "highlights", neither of which this app does (no video, no live
 * scores feed) -- adapted to the reference's *visual language* (dark
 * stadium-glow gradient, large hero visual, headline + subtext, a
 * bright-green pill CTA) with copy honest about what this app actually
 * is: one team name in, the full stats report out.
 */
@Composable
fun OnboardingScreen(onGetStarted: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize().background(Color(0xFF0A130C))) {
        StadiumGlow()

        Column(
            modifier = Modifier.fillMaxSize().padding(horizontal = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
                HeroBadge()
            }

            Text(
                "Every match,\nfully broken down.",
                color = Color.White,
                fontSize = 30.sp,
                fontWeight = FontWeight.Bold,
                lineHeight = 36.sp,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                "Search any team and get the full picture -- form, lineups, " +
                    "predictions, and everything else the numbers say, in one report.",
                color = Color.White.copy(alpha = 0.7f),
                fontSize = 14.sp,
                lineHeight = 20.sp,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(32.dp))
            Button(
                onClick = onGetStarted,
                colors = ButtonDefaults.buttonColors(containerColor = AppTheme.colors.brandBright, contentColor = Color(0xFF0A130C)),
                shape = MaterialTheme.shapes.extraLarge,
                modifier = Modifier.fillMaxWidth().height(56.dp),
            ) {
                Text("Get started", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            }
            Spacer(Modifier.height(40.dp))
        }
    }
}

@Composable
private fun HeroBadge() {
    Box(contentAlignment = Alignment.Center) {
        Canvas(modifier = Modifier.size(220.dp)) {
            drawCircle(
                brush =
                    Brush.radialGradient(
                        colors = listOf(Color(0xFF8FD13F).copy(alpha = 0.35f), Color.Transparent),
                    ),
                radius = size.minDimension / 2,
            )
        }
        Logo(size = 96.dp)
    }
}

/** Two soft radial glows near the top, evoking floodlights against a
 * dark stadium sky -- decorative only, matches the reference's
 * background treatment without needing a photo asset. */
@Composable
private fun StadiumGlow() {
    Canvas(modifier = Modifier.fillMaxSize()) {
        val glow =
            Brush.radialGradient(
                colors = listOf(Color(0xFF1E5E2E).copy(alpha = 0.55f), Color.Transparent),
                center = Offset(size.width * 0.5f, size.height * 0.02f),
                radius = size.width * 0.9f,
            )
        drawRect(brush = glow)
    }
}
