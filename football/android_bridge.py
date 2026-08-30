"""Holds the Android application Context object, handed in once from
Kotlin (MainActivity.kt, right after Python.start()) rather than
fetched from the Python side -- keeps this module import-safe on
desktop (no java/android imports at module level) and avoids relying on
any particular Chaquopy API for retrieving the context back out of the
platform object, which isn't documented as a stable Python-facing
surface.

Only meaningful on Android; browser.py's WebView backend is the only
consumer.
"""

from __future__ import annotations

from typing import Any, Optional

_application_context: Optional[Any] = None


def set_application_context(context: Any) -> None:
    global _application_context
    _application_context = context


def get_application_context() -> Any:
    if _application_context is None:
        raise RuntimeError(
            "Android application context not set -- call "
            "football.android_bridge.set_application_context(context) "
            "from Kotlin/Java right after Python.start()."
        )
    return _application_context
