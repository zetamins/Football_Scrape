package com.football.app.queue

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class QueueStateTest {
    @Test
    fun `Running instances with the same fields are equal`() {
        val a = QueueState.Running(currentTeam = "Arsenal", index = 0, total = 3, message = "Working")
        val b = QueueState.Running(currentTeam = "Arsenal", index = 0, total = 3, message = "Working")
        assertEquals(a, b)
        assertEquals(a.hashCode(), b.hashCode())
    }

    @Test
    fun `Running instances with a different field are not equal`() {
        val a = QueueState.Running(currentTeam = "Arsenal", index = 0, total = 3, message = "Working")
        val b = a.copy(index = 1)
        assertNotEquals(a, b)
        assertEquals(1, b.index)
        assertEquals("Arsenal", b.currentTeam)
    }

    @Test
    fun `Finished instances with the same fields are equal`() {
        val a = QueueState.Finished(succeeded = 2, failed = 1, lastError = "timeout")
        val b = QueueState.Finished(succeeded = 2, failed = 1, lastError = "timeout")
        assertEquals(a, b)
        assertEquals(a.hashCode(), b.hashCode())
    }

    @Test
    fun `Finished copy overrides just the requested field`() {
        val a = QueueState.Finished(succeeded = 2, failed = 1, lastError = "timeout")
        val b = a.copy(lastError = null)
        assertEquals(2, b.succeeded)
        assertEquals(1, b.failed)
        assertEquals(null, b.lastError)
    }

    @Test
    fun `Idle is a singleton object`() {
        assertEquals(QueueState.Idle, QueueState.Idle)
    }

    @Test
    fun `toString includes the class name for Running and Finished`() {
        assert(QueueState.Running("Arsenal", 0, 3, "Working").toString().contains("Running"))
        assert(QueueState.Finished(2, 1, null).toString().contains("Finished"))
    }
}
