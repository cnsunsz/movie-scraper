"""DMM public search. Age-check and blocks are reported, not bypassed."""

from __future__ import annotations

import urllib.parse

from scraper.imdb import MovieMetadata
from scraper.net import HttpError, fetch

TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class DmmError(Exception):
    pass


def lookup_code(code: str, *, proxy: str | None = None) -> MovieMetadata | None:
    query = (code or "").strip()
    if not query:
        return None
    url = "https://www.dmm.co.jp/search/=/searchstr=" + urllib.parse.quote(query) + "/"
    try:
        status, body = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "text/html", "Accept-Language": "ja,en;q=0.8"},
            attempts=2,
        )
    except HttpError as exc:
        raise DmmError(f"DMM HTTP {exc.status or ''}，未尝试绕过".replace("  ", " ")) from exc
    text = body.decode("utf-8", "replace")
    lowered = text[:4000].lower()
    if "age_check" in lowered or "年齢" in text[:4000] or status in {401, 403}:
        raise DmmError(f"DMM 返回年龄验证或拒绝访问（HTTP {status}），未尝试绕过")
    if query.replace("-", "").lower() not in text.replace("-", "").lower():
        return None
    return None
