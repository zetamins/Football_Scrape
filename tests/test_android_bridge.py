import pytest

from football import android_bridge


def test_get_application_context_raises_when_never_set(monkeypatch):
    monkeypatch.setattr(android_bridge, "_application_context", None)
    with pytest.raises(RuntimeError, match="Android application context not set"):
        android_bridge.get_application_context()


def test_set_and_get_application_context_roundtrip(monkeypatch):
    monkeypatch.setattr(android_bridge, "_application_context", None)
    sentinel = object()
    android_bridge.set_application_context(sentinel)
    assert android_bridge.get_application_context() is sentinel
