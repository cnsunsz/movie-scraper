"""Strict comparisons shared by every metadata site."""

from __future__ import annotations

import re

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_CODE_RE = re.compile(r"[\s_\-]+")


class CodeMismatch(Exception):
    """The page was a different number than the filename."""

    def __init__(self, page_code: str = "") -> None:
        self.page_code = page_code
        shown = page_code or "空"
        super().__init__(f"番号对不上（页面 {shown}）")


def normalize_title(text: str) -> str:
    """Lowercase title with the year and punctuation removed."""

    cleaned = _YEAR_RE.sub(" ", text or "")
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def normalize_code(code: str) -> str:
    return _CODE_RE.sub("", code or "").upper()


def codes_equal(left: str, right: str) -> bool:
    a = normalize_code(left)
    b = normalize_code(right)
    return bool(a) and a == b


def accept_code(movie, wanted: str):
    """Return ``movie`` only when its number equals ``wanted``. Otherwise ``None``."""

    if movie is None or not codes_equal(getattr(movie, "code", ""), wanted):
        return None
    return movie
