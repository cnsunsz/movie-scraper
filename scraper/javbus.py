"""JavBus detail page for a studio code. Standard library only.

``GET https://www.javbus.com/{CODE}`` with the code uppercased.
A challenge page or HTTP 403 is reported and not bypassed.
"""

from __future__ import annotations

import html
import re
import urllib.parse

from scraper.imdb import MovieMetadata
from scraper.javdb import preview_stills
from scraper.match import CodeMismatch, accept_code
from scraper.net import HttpError, fetch

SITE = "https://www.javbus.com"
TIMEOUT = 20
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_CHALLENGE = ("just a moment", "cf-challenge", "attention required", "cf-turnstile")


class JavbusError(Exception):
    """JavBus refused the request or the page is a challenge."""


def lookup_code(code: str, *, proxy: str | None = None) -> MovieMetadata | None:
    query = (code or "").strip()
    if not query:
        return None
    url = f"{SITE}/{urllib.parse.quote(query.upper())}"
    page = _get_text(url, proxy=proxy)
    if not page:
        return None
    movie = parse_detail_html(page, url)
    if not movie.title:
        movie.title = movie.code or query
    accepted = accept_code(movie, query)
    if accepted is None:
        raise CodeMismatch(movie.code)
    return accepted


def parse_detail_html(page_html: str, page_url: str = "") -> MovieMetadata:
    """Map a JavBus movie page. No network."""

    code = _header_plain(page_html, "識別碼") or _header_plain(page_html, "识别码")
    heading = _text(_tag(page_html, "h3"))
    title = heading
    if code and heading.upper().startswith(code.upper()):
        title = heading[len(code):].strip()
    premiered = _header_plain(page_html, "發行日期") or _header_plain(page_html, "发行日期")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", premiered):
        premiered = ""
    year = premiered[:4] if premiered else ""
    runtime = _first_number(_header_plain(page_html, "長度") or _header_plain(page_html, "长度"))
    director = _header_plain(page_html, "導演") or _header_plain(page_html, "导演")
    studio = _header_plain(page_html, "製作商") or _header_plain(page_html, "制作商")
    label = _header_plain(page_html, "發行商") or _header_plain(page_html, "发行商") or studio
    series = _header_plain(page_html, "系列")
    genres = _anchor_texts(page_html, "genre")
    actors, actor_photos = _stars(page_html)
    cover = _abs(_attr(page_html, "bigImage", "href") or _img_in(page_html, "bigImage"))
    stills = _samples(page_html)
    display = title or code
    return MovieMetadata(
        title=display,
        original_title=display,
        year=year,
        premiered=premiered,
        runtime=runtime,
        genres=genres,
        directors=[director] if director else [],
        cast=actors,
        actor_photos=actor_photos,
        poster_url=cover,
        fanart_url=cover,
        thumb_url=cover,
        studio=studio,
        label=label,
        tags=genres + ([series] if series and series not in genres else []),
        code=code,
        series=series,
        source="javbus",
        extra_stills=stills,
    )


def _get_text(url: str, *, proxy: str | None) -> str:
    try:
        status, body = fetch(url, proxy=proxy, timeout=TIMEOUT, headers=_HEADERS, attempts=2)
    except HttpError as exc:
        if exc.status in {401, 403, 429}:
            raise JavbusError(f"JavBus HTTP {exc.status}，未尝试绕过") from exc
        if exc.status == 404:
            return ""
        raise JavbusError(f"JavBus 请求失败: {exc}") from exc
    if status == 404:
        return ""
    if status >= 400:
        raise JavbusError(f"JavBus HTTP {status}，未尝试绕过")
    text = body.decode("utf-8", "replace")
    sample = text[:8000].lower()
    if any(marker in sample for marker in _CHALLENGE):
        raise JavbusError("JavBus 返回了验证页，未尝试绕过")
    return text


def _header_plain(page_html: str, label: str) -> str:
    match = re.search(
        rf'<span class="header">\s*{re.escape(label)}\s*:?\s*</span>\s*(.*?)</p>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _text(match.group(1)) if match else ""


def _anchor_texts(page_html: str, class_name: str) -> list[str]:
    found = []
    for match in re.finditer(
        rf'<span class="{re.escape(class_name)}"[^>]*>\s*(?:<label[^>]*>)?\s*(?:<input[^>]*>)?\s*<a[^>]*>(.*?)</a>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        name = _text(match.group(1))
        if name and name not in found:
            found.append(name)
    return found


def _stars(page_html: str) -> tuple[list[str], dict[str, str]]:
    names: list[str] = []
    photos: dict[str, str] = {}
    for match in re.finditer(
        r'class="star-box[\s\S]{0,1500}?<div class="star-name">\s*<a[^>]*>(.*?)</a>',
        page_html or "",
        flags=re.IGNORECASE,
    ):
        block = match.group(0)
        name = _text(match.group(1))
        if not name or name in names:
            continue
        names.append(name)
        image = re.search(r'<img[^>]+src="([^"]+)"', block, flags=re.IGNORECASE)
        if image:
            photos[name] = _abs(image.group(1))
    return names, photos



def _samples(page_html: str) -> list[str]:
    found = []
    for match in re.finditer(
        r'<a[^>]*class="[^"]*sample-box[^"]*"[^>]*href="([^"]+)"'
        r'|<a[^>]*href="([^"]+)"[^>]*class="[^"]*sample-box[^"]*"',
        page_html,
        flags=re.IGNORECASE,
    ):
        url = _abs(html.unescape(match.group(1) or match.group(2) or ""))
        if url and url not in found and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", url, re.I):
            found.append(url)
        if len(found) >= 20:
            break
    if not found:
        # keep the helper imported for callers that reuse the JavDB still parser on mixed pages
        found = [url for url in preview_stills(page_html) if "sample" in url.lower()]
    return found[:20]


def _attr(page_html: str, class_name: str, attr: str) -> str:
    match = re.search(
        rf'<a[^>]*class="[^"]*{re.escape(class_name)}[^"]*"[^>]*{attr}="([^"]+)"'
        rf'|<a[^>]*{attr}="([^"]+)"[^>]*class="[^"]*{re.escape(class_name)}[^"]*"',
        page_html,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return html.unescape(match.group(1) or match.group(2) or "")


def _img_in(page_html: str, class_name: str) -> str:
    match = re.search(
        rf'<a[^>]*class="[^"]*{re.escape(class_name)}[^"]*"[^>]*>\s*<img[^>]*src="([^"]+)"',
        page_html,
        flags=re.IGNORECASE,
    )
    return html.unescape(match.group(1)) if match else ""


def _abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return SITE + url
    return url


def _text(fragment: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip(" ,")


def _tag(page_html: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", page_html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _first_number(value: str) -> str:
    match = re.search(r"(\d+)", value or "")
    return match.group(1) if match else ""
