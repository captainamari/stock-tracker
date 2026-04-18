"""
Lightweight i18n module for Stock Tracker.

Usage:
    from web.i18n import get_translator, set_language, SUPPORTED_LANGUAGES

    t = get_translator("en")
    t("nav.dashboard")  # -> "Dashboard"
"""

from web.i18n.core import (
    get_translator,
    translate,
    get_language_from_request,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
)

__all__ = [
    "get_translator",
    "translate",
    "get_language_from_request",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
]
