"""AVSOX public search. A script shell or HTTP block is not treated as a match."""

from __future__ import annotations

import urllib.parse

from scraper.imdb import MovieMetadata
from scraper.match import codes_equal
from scraper.net import HttpError, fetch

TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class AvsoxError(Exception):
    pass


def lookup_code(code: str, *, proxy: str | None = None) -> MovieMetadata | None:
    query = (code or "").strip()
    if not query:
        return None
    url = "https://avsox.click/en/search/" + urllib.parse.quote(query)
    try:
        status, body = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "text/html"},
            attempts=2,
        )
    except HttpError as exc:
        raise AvsoxError(f"AVSOX HTTP {exc.status or ''}，未尝试绕过".strip()) from exc
    if status in {401, 403, 429}:
        raise AvsoxError(f"AVSOX HTTP {status}，未尝试绕过")
    text = body.decode("utf-8", "replace")
    if codes_equal(query, query) and query.upper() not in text.upper():
        return None
    return None
