"""
i18n core — language pack loading, translation lookup, request language detection.
"""

import json
from pathlib import Path
from typing import Callable, Optional

# ============================================================
# Constants
# ============================================================
SUPPORTED_LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"

LOCALES_DIR = Path(__file__).parent / "locales"

# ============================================================
# Load language packs (cached in memory)
# ============================================================
_packs: dict[str, dict] = {}


def _load_pack(lang: str) -> dict:
    """Load a JSON language pack, with caching."""
    if lang in _packs:
        return _packs[lang]

    fp = LOCALES_DIR / f"{lang}.json"
    if not fp.exists():
        _packs[lang] = {}
        return _packs[lang]

    with open(fp, "r", encoding="utf-8") as f:
        _packs[lang] = json.load(f)
    return _packs[lang]


def reload_packs():
    """Force-reload all language packs (useful during development)."""
    _packs.clear()
    for lang in SUPPORTED_LANGUAGES:
        _load_pack(lang)


# ============================================================
# Translation lookup
# ============================================================
def translate(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """
    Look up *key* (dot-separated, e.g. "nav.dashboard") in the language pack.

    Falls back to English, then returns the key itself if not found.
    Supports simple ``{placeholder}`` interpolation via **kwargs.
    """
    pack = _load_pack(lang)
    value = _resolve(pack, key)

    # Fallback to English
    if value is None and lang != DEFAULT_LANGUAGE:
        en_pack = _load_pack(DEFAULT_LANGUAGE)
        value = _resolve(en_pack, key)

    if value is None:
        return key  # last resort

    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return value


def _resolve(pack: dict, key: str):
    """Walk nested dict by dot-separated key."""
    parts = key.split(".")
    node = pack
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return None
    return node if isinstance(node, str) else None


# ============================================================
# Translator factory (returns a callable)
# ============================================================
def get_translator(lang: str = DEFAULT_LANGUAGE) -> Callable[..., str]:
    """Return a translation function bound to a specific language."""

    def _t(key: str, **kwargs) -> str:
        return translate(key, lang=lang, **kwargs)

    _t.lang = lang  # type: ignore[attr-defined]
    return _t


# ============================================================
# Detect language from request
# ============================================================
def get_language_from_request(request) -> str:
    """
    Determine UI language from the request, in priority order:
    1. ?lang=xx query parameter
    2. lang cookie
    3. Accept-Language header
    4. DEFAULT_LANGUAGE
    """
    # 1. Query parameter
    lang = request.query_params.get("lang", "").lower()
    if lang in SUPPORTED_LANGUAGES:
        return lang

    # 2. Cookie
    lang = (request.cookies.get("lang") or "").lower()
    if lang in SUPPORTED_LANGUAGES:
        return lang

    # 3. Accept-Language header
    accept = request.headers.get("accept-language", "")
    for part in accept.split(","):
        code = part.split(";")[0].strip().lower()
        if code.startswith("zh"):
            return "zh"
        if code.startswith("en"):
            return "en"

    return DEFAULT_LANGUAGE
