"""FC2 article page for an FC2-PPV / FC2 number. Age gates are not bypassed."""

from __future__ import annotations

import re

from scraper.imdb import MovieMetadata
from scraper.net import HttpError, fetch

TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class Fc2Error(Exception):
    pass


def fc2_id(code: str) -> str:
    """Digits from ``FC2-PPV-123456`` or ``FC2-123456``. Empty if it is not FC2."""

    text = (code or "").upper().replace(" ", "")
    match = re.search(r"FC2(?:-?PPV)?-?(\d{5,8})", text)
    return match.group(1) if match else ""


def lookup_code(code: str, *, proxy: str | None = None) -> MovieMetadata | None:
    number = fc2_id(code)
    if not number:
        return None
    url = f"https://adult.contents.fc2.com/article/{number}/"
    try:
        status, body = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "text/html"},
            attempts=2,
        )
    except HttpError as exc:
        raise Fc2Error(f"FC2 HTTP {exc.status or ''}，未尝试绕过".strip()) from exc
    text = body.decode("utf-8", "replace")
    lowered = text[:4000].lower()
    if "ekyc" in lowered or "age verification" in lowered or "年齢" in text[:4000]:
        raise Fc2Error(f"FC2 跳转到年龄验证（HTTP {status}），未尝试绕过")
    if status in {401, 403, 429}:
        raise Fc2Error(f"FC2 HTTP {status}，未尝试绕过")
    if number not in text:
        return None
    return None
