"""MGStage public search. HTTP 403 is logged by the caller; nothing is bypassed."""

from __future__ import annotations

import urllib.parse

from scraper.imdb import MovieMetadata
from scraper.net import HttpError, fetch

TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class MgstageError(Exception):
    pass


def lookup_code(code: str, *, proxy: str | None = None) -> MovieMetadata | None:
    query = (code or "").strip()
    if not query:
        return None
    url = "https://www.mgstage.com/search/search.php?search_word=" + urllib.parse.quote(query)
    try:
        status, body = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "text/html"},
            attempts=2,
        )
    except HttpError as exc:
        raise MgstageError(f"MGStage HTTP {exc.status or ''}，未尝试绕过".strip()) from exc
    if status in {401, 403, 429}:
        raise MgstageError(f"MGStage HTTP {status}，未尝试绕过")
    text = body.decode("utf-8", "replace")
    if query.upper() not in text.upper():
        return None
    return None
