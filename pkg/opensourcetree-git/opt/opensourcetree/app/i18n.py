"""
Lightweight translation engine for OpenSourceTree.

Usage:
    from app.i18n import t
    label = QLabel(t("toolbar.fetch"))

JSON format (locales/<code>.json):
    {
        "_name": "English",   # native language name shown in dropdown
        "_code": "en",
        "some.key": "Some text",
        "greeting": "Hello, {name}!"
    }
"""
import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent.parent / "locales"

_strings: dict[str, str] = {}
_fallback: dict[str, str] = {}  # English as fallback
_current_lang: str = "en"


def available_languages() -> list[tuple[str, str]]:
    """Return list of (code, native_name) from all *.json files in locales/."""
    langs = []
    for path in sorted(LOCALES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("_name", path.stem)
            langs.append((path.stem, name))
        except Exception:
            pass
    return langs


def load_language(code: str) -> None:
    """Load a language by its file code (e.g. 'en', 'ru')."""
    global _strings, _fallback, _current_lang

    en_path = LOCALES_DIR / "en.json"
    if en_path.exists():
        try:
            _fallback = json.loads(en_path.read_text(encoding="utf-8"))
        except Exception:
            _fallback = {}

    if code == "en":
        _strings = _fallback
    else:
        path = LOCALES_DIR / f"{code}.json"
        if path.exists():
            try:
                _strings = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                _strings = dict(_fallback)
        else:
            _strings = dict(_fallback)

    _current_lang = code


def t(key: str, **kwargs) -> str:
    """
    Translate a key.  Falls back to English, then to the key itself.
    Supports str.format() placeholders: t("greeting", name="World")
    """
    text: str = _strings.get(key) or _fallback.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            pass
    return text


def current_language() -> str:
    return _current_lang
