"""Optional JavDB lookup for number-style filenames. Standard library only.

Search ``https://javdb.com/search?q={code}&f=all``, open the first ``/v/``
result, and read the public detail page. A challenge page or HTTP 403 is
reported and not bypassed.
"""

from __future__ import annotations

import html
import re
import urllib.parse

from scraper.imdb import MovieMetadata
from scraper.match import CodeMismatch, accept_code, codes_equal
from scraper.net import HttpError, fetch

SEARCH_URL = "https://javdb.com/search?q={query}&f=all"
SITE = "https://javdb.com"
TIMEOUT = 20
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_VIDEO_HREF = re.compile(r'href="(/v/[A-Za-z0-9]+)(?:\?[^"]*)?"')
_CHALLENGE = (
    "just a moment",
    "cf-challenge",
    "cf-browser-verification",
    "attention required",
    "cf-turnstile",
)


class JavdbError(Exception):
    """JavDB refused the request or returned a challenge page."""


def lookup_code(code: str, *, proxy: str | None = None) -> MovieMetadata | None:
    """Search one studio code and return parsed metadata, or None if no hit."""

    query = (code or "").strip()
    if not query:
        return None
    search_html = _get_text(SEARCH_URL.format(query=urllib.parse.quote(query)), proxy=proxy)
    path = matching_video_path(search_html, query)
    if not path:
        if _is_challenge(search_html):
            raise JavdbError("JavDB 返回了验证页或空页面，未尝试绕过")
        return None
    page_url = path if path.startswith("http") else SITE + path
    detail_html = _get_text(page_url, proxy=proxy)
    if _is_challenge(detail_html) and 'class="video-detail"' not in detail_html:
        raise JavdbError("JavDB 详情页是验证页，未尝试绕过")
    movie = parse_detail_html(detail_html, page_url)
    if not movie.title and not movie.javdb_id:
        return None
    accepted = accept_code(movie, query)
    if accepted is None:
        raise CodeMismatch(movie.code)
    return accepted


def first_video_path(page_html: str) -> str | None:
    """First ``/v/<id>`` link on a search page."""

    match = _VIDEO_HREF.search(page_html or "")
    return match.group(1) if match else None


def matching_video_path(page_html: str, code: str) -> str | None:
    """``/v/`` link whose listed number equals ``code``. The first link is not enough."""

    pattern = re.compile(
        r'<a href="(/v/[A-Za-z0-9]+)"[\s\S]{0,1200}?<strong>\s*([^<]+?)\s*</strong>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(page_html or ""):
        if codes_equal(match.group(2), code):
            return match.group(1)
    return None


def parse_detail_html(page_html: str, page_url: str = "") -> MovieMetadata:
    """Map a JavDB movie page onto :class:`MovieMetadata`. No network."""

    title = _text_of(_attr_text(page_html, "current-title"))
    original = _text_of(_attr_text(page_html, "origin-title")) or title
    code = _collapse_code(_field(page_html, "番號") or _field(page_html, "番号"))
    premiered = _field(page_html, "日期")
    year = premiered[:4] if len(premiered) >= 4 and premiered[:4].isdigit() else ""
    runtime = _first_number(_field(page_html, "時長") or _field(page_html, "时长"))
    director = _field(page_html, "導演") or _field(page_html, "导演")
    studio = _field(page_html, "片商")
    genres = _split_list(_field(page_html, "類別") or _field(page_html, "类别"))
    actors, actor_photos = _actor_entries(page_html)
    series = _field(page_html, "系列")
    tags = list(genres)
    if series and series not in tags:
        tags.append(series)
    rating = _rating(_field(page_html, "評分") or _field(page_html, "评分"))
    plot = _field(page_html, "簡介") or _field(page_html, "简介") or _field(page_html, "劇情")
    cover = _img_src(page_html, "video-cover")
    label = _field(page_html, "發行") or _field(page_html, "发行") or studio
    javdb_id = ""
    match = re.search(r"/v/([A-Za-z0-9]+)", page_url or "")
    if match:
        javdb_id = match.group(1)
    display = title or original or code
    return MovieMetadata(
        title=display,
        original_title=original or display,
        year=year,
        premiered=premiered if re.fullmatch(r"\d{4}-\d{2}-\d{2}", premiered) else "",
        plot=plot,
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
        tags=tags,
        code=code,
        series=series,
        javdb_id=javdb_id,
        rating=rating,
        source="javdb",
        extra_stills=preview_stills(page_html),
    )


def _get_text(url: str, *, proxy: str | None) -> str:
    try:
        status, body = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT,
            headers=_HEADERS,
            limit=2_000_000,
            attempts=2,
        )
    except HttpError as exc:
        if exc.status in {401, 403, 429}:
            raise JavdbError(f"JavDB 拒绝访问（HTTP {exc.status}），未尝试绕过") from exc
        raise JavdbError(f"JavDB 请求失败: {exc}") from exc
    if status >= 400:
        raise JavdbError(f"JavDB 拒绝访问（HTTP {status}），未尝试绕过")
    if not body.strip():
        raise JavdbError("JavDB 返回了空页面")
    text = body.decode("utf-8", "replace")
    if status == 200 and _is_challenge(text) and "/v/" not in text and "video-detail" not in text:
        raise JavdbError("JavDB 返回了验证页，未尝试绕过")
    return text


def _is_challenge(page_html: str) -> bool:
    sample = (page_html or "")[:20000].lower()
    return any(marker in sample for marker in _CHALLENGE)



def _actor_entries(page_html: str) -> tuple[list[str], dict[str, str]]:
    """Names plus any photo URL sitting on the same actor link."""

    match = re.search(
        r"<strong>\s*(?:演員|演员)\s*:?\s*</strong>\s*(?:&nbsp;)?\s*"
        r'<span class="value">(.*?)</span>',
        page_html or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    fragment = match.group(1) if match else ""
    names: list[str] = []
    photos: dict[str, str] = {}
    for link in re.finditer(r"<a\b[^>]*>(.*?)</a>", fragment, flags=re.IGNORECASE | re.DOTALL):
        inner = link.group(1)
        image = re.search(r'\bsrc="([^"]+)"', inner, flags=re.IGNORECASE)
        name = _text_of(re.sub(r"<img\b[^>]*>", " ", inner, flags=re.IGNORECASE))
        if not name or name in names:
            continue
        names.append(name)
        if image:
            url = html.unescape(image.group(1))
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                photos[name] = url
    if not names:
        names = _split_list(_field(page_html, "演員") or _field(page_html, "演员"))
    return names, photos


def _field(page_html: str, label: str) -> str:
    match = re.search(
        rf"<strong>\s*{re.escape(label)}\s*:?\s*</strong>\s*(?:&nbsp;)?\s*"
        rf'<span class="value">(.*?)</span>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return _text_of(match.group(1))


def _attr_text(page_html: str, class_name: str) -> str:
    match = re.search(
        rf'class="{re.escape(class_name)}"[^>]*>(.*?)</',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def _text_of(fragment: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip(" ,")


def _collapse_code(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _split_list(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,，、]", value)
    return [part.strip() for part in parts if part.strip()]


def _first_number(value: str) -> str:
    match = re.search(r"(\d+)", value or "")
    return match.group(1) if match else ""


def _rating(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", value or "")
    return match.group(1) if match else ""


def _img_src(page_html: str, class_name: str) -> str:
    for match in re.finditer(r"<img\b[^>]*>", page_html, flags=re.IGNORECASE):
        tag = match.group(0)
        if class_name not in tag:
            continue
        src = re.search(r'\bsrc="([^"]+)"', tag)
        if src and src.group(1).startswith("http"):
            return html.unescape(src.group(1))
    return ""


def preview_stills(page_html: str, limit: int = 20) -> list[str]:
    """Large preview stills from a JavDB detail page. Empty if none."""

    found: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'<a\b[^>]*class="[^"]*tile-item[^"]*"[^>]*href="(https?://[^"]+)"'
        r'|<a\b[^>]*href="(https?://[^"]+)"[^>]*class="[^"]*tile-item[^"]*"',
        re.IGNORECASE,
    )
    for match in pattern.finditer(page_html or ""):
        url = html.unescape(match.group(1) or match.group(2) or "")
        if not re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", url, re.IGNORECASE):
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            break
    return found
