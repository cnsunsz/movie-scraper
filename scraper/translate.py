"""Translate a plot to simplified Chinese when it has no CJK characters.

Uses the public Google translate endpoint (no API key). Failure returns the
original text so the caller can keep it and log one line.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from scraper.net import HttpError, fetch

_CJK = re.compile(r"[\u4e00-\u9fff]")
# Public no-key endpoints. The first one is often rate-limited; the second is the fallback.
_ENDPOINTS = (
    (
        "https://translate.googleapis.com/translate_a/single",
        ("client", "gtx"),
    ),
    (
        "https://clients5.google.com/translate_a/t",
        ("client", "dict-chrome-ex"),
    ),
)


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def translate_to_zh(text: str, *, proxy: str | None = None) -> str:
    """Return simplified Chinese, or raise if the endpoint fails."""

    query = (text or "").strip()
    if not query:
        return ""
    if has_cjk(query):
        return query
    last_error: Exception | None = None
    for base, client in _ENDPOINTS:
        params = {"client": client[1], "sl": "auto", "tl": "zh-CN", "q": query}
        if "single" in base:
            params["dt"] = "t"
        url = base + "?" + urllib.parse.urlencode(params)
        try:
            _status, body = fetch(
                url,
                proxy=proxy,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                limit=1_000_000,
                attempts=2,
            )
            payload = json.loads(body.decode("utf-8"))
        except (HttpError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
        translated = _translated_text(payload)
        if translated:
            return translated
        last_error = RuntimeError("翻译结果为空")
    raise RuntimeError(f"翻译请求失败: {last_error}")


def _translated_text(payload) -> str:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return ""
    first = payload[0]
    if first and isinstance(first[0], str):
        return first[0].strip()
    parts: list[str] = []
    for chunk in first:
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], str):
            parts.append(chunk[0])
    return "".join(parts).strip()
