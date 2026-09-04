package com.football.app

import android.graphics.Bitmap
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Canvas
import androidx.compose.ui.graphics.drawscope.CanvasDrawScope
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection

/**
 * Invokes [block] against a real `DrawScope` backed by a real (but
 * off-screen, never rendered anywhere) `android.graphics.Canvas`/`Bitmap`
 * pair -- confirmed this session that Kover credits statements inside a
 * plain `DrawScope` extension function invoked this way as executed,
 * unlike the same statements inline in a Compose `Canvas{}} draw lambda
 * under Robolectric (which never shows as covered no matter how the
 * composable itself is rendered/tested -- a Robolectric/Compose UI
 * pipeline limitation, not something this bypasses incorrectly: this
 * calls the exact same drawing code as the real Canvas{} block, just
 * through `CanvasDrawScope().draw(...)` directly rather than through
 * Compose's own composition + draw-phase machinery). [widthPx]/[heightPx]
 * default to a modest, arbitrary real size -- most of these draw
 * functions only use proportions of `size`, not literal pixel values,
 * so the exact number rarely matters; callers needing a specific aspect
 * ratio (the pitch diagram, roughly 0.72) pass one in.
 */
internal fun runDrawScope(
    widthPx: Float = 200f,
    heightPx: Float = 200f,
    block: DrawScope.() -> Unit,
) {
    val bitmap = Bitmap.createBitmap(widthPx.toInt().coerceAtLeast(1), heightPx.toInt().coerceAtLeast(1), Bitmap.Config.ARGB_8888)
    val nativeCanvas = android.graphics.Canvas(bitmap)
    CanvasDrawScope().draw(
        density = Density(1f),
        layoutDirection = LayoutDirection.Ltr,
        canvas = Canvas(nativeCanvas),
        size = Size(widthPx, heightPx),
        block = block,
    )
}
