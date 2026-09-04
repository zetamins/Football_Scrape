package com.football.app.queue

/**
 * In-app observable mirror of what SearchQueueService is doing --
 * separate from the notification (which is the primary, required
 * "still running in the background" signal), this just lets SearchScreen
 * show a small live status card too when the app happens to be open.
 */
sealed interface QueueState {
    data object Idle : QueueState

    data class Running(
        val currentTeam: String,
        val index: Int,
        val total: Int,
        val message: String,
    ) : QueueState

    // lastError is the most recent team's failure message, if any --
    // meaningful for a queue-of-one (SearchScreen's single-search path
    // shows it directly, matching what a direct SearchState.Error used
    // to show), ambiguous for a true multi-team batch (only the LAST
    // failure survives) but harmless there since the batch UI shows
    // succeeded/failed counts, not this message.
    data class Finished(
        val succeeded: Int,
        val failed: Int,
        val lastError: String? = null,
    ) : QueueState
}
