"""Optional IMDb metadata via the public Stremio Cinemeta JSON API.

No API key and no IMDb HTML scraping.

* Search: ``https://v3-cinemeta.strem.io/catalog/movie/top/search={query}.json``
* By id: ``https://v3-cinemeta.strem.io/meta/movie/{imdbId}.json``

Verified shape (2026-10): search results live in ``metas``; a direct lookup
wraps the movie in ``meta``. Titles use ``name``, the plot is ``description``,
runtime looks like ``"148 min"``, and ``director`` / ``cast`` / ``genres`` are
lists. Cinemeta usually does not send a separate original title.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from scraper.match import normalize_title

USER_AGENT = "MovieScraper/1.0 (local media-library metadata tool)"
TIMEOUT_SECONDS = 15
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_IMDB_ID_RE = re.compile(r"tt\d{7,8}")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

SEARCH_URL = "https://v3-cinemeta.strem.io/catalog/movie/top/search={query}.json"
META_URL = "https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"


class ImdbError(Exception):
    """A Cinemeta request failed after its retry."""


@dataclass
class MovieMetadata:
    title: str = ""
    original_title: str = ""
    year: str = ""
    premiered: str = ""
    plot: str = ""
    runtime: str = ""
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    poster_url: str = ""
    fanart_url: str = ""
    imdb_id: str = ""
    rating: str = ""
    source: str = ""
    studio: str = ""
    tags: list[str] = field(default_factory=list)
    javdb_id: str = ""
    tmdb_id: str = ""
    code: str = ""
    series: str = ""
    label: str = ""
    thumb_url: str = ""
    extra_stills: list[str] = field(default_factory=list)
    actor_photos: dict[str, str] = field(default_factory=dict)


def fetch_by_id(imdb_id: str, *, proxy: str | None = None) -> MovieMetadata | None:
    """Load one movie by IMDb id. ``None`` if Cinemeta has no record.

    Network and HTTP failures raise :class:`ImdbError` after one retry.
    """

    imdb_id = (imdb_id or "").strip().lower()
    if not _IMDB_ID_RE.fullmatch(imdb_id):
        raise ImdbError(f"无效的 IMDb id: {imdb_id}")
    payload = _get_json(META_URL.format(imdb_id=urllib.parse.quote(imdb_id)), proxy=proxy)
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return None
    movie = metadata_from_dict(meta)
    if not movie.title and not movie.imdb_id:
        return None
    if not movie.imdb_id:
        movie.imdb_id = imdb_id
    return movie


def search_title(query: str, year: str | None = None, *, proxy: str | None = None) -> MovieMetadata | None:
    """Search by cleaned title and return the best full record.

    The catalog row is only a summary, so the chosen id is loaded again.
    If that second call fails, the summary row is returned instead.
    """

    query = (query or "").strip()
    if not query:
        return None
    search_query = query
    if year and year not in query:
        search_query = f"{query} {year}"
    url = SEARCH_URL.format(query=urllib.parse.quote(search_query, safe=""))
    payload = _get_json(url, proxy=proxy)
    metas = payload.get("metas") if isinstance(payload, dict) else None
    if not isinstance(metas, list):
        return None
    chosen = _choose(metas, query, year)
    if not chosen:
        return None
    imdb_id = str(chosen.get("imdb_id") or chosen.get("id") or "")
    if _IMDB_ID_RE.fullmatch(imdb_id):
        try:
            full = fetch_by_id(imdb_id, proxy=proxy)
        except ImdbError:
            full = None
        if full is not None:
            return full
    movie = metadata_from_dict(chosen)
    return movie if movie.title else None


def metadata_from_dict(raw: dict) -> MovieMetadata:
    """Map a Cinemeta movie object (full or search row) onto our fields."""

    title = _text(raw.get("name") or raw.get("title"))
    original = _text(
        raw.get("originalName")
        or raw.get("originalTitle")
        or raw.get("originaltitle")
    )
    premiered = _date(raw.get("released"))
    year = _year(raw.get("year")) or _year(raw.get("releaseInfo")) or _year(premiered)
    imdb_id = str(raw.get("imdb_id") or raw.get("id") or "").strip().lower()
    if not _IMDB_ID_RE.fullmatch(imdb_id):
        imdb_id = ""
    return MovieMetadata(
        title=title,
        original_title=original or title,
        year=year,
        premiered=premiered,
        plot=_text(raw.get("description") or raw.get("plot")),
        runtime=_runtime(raw.get("runtime")),
        genres=_names(raw.get("genres") or raw.get("genre")),
        directors=_names(raw.get("director")),
        cast=_names(raw.get("cast")),
        actor_photos=_actor_photos(raw.get("cast")),
        poster_url=_http_url(raw.get("poster")),
        fanart_url=_http_url(raw.get("background") or raw.get("fanart")),
        imdb_id=imdb_id,
        rating=_rating(raw.get("imdbRating") if raw.get("imdbRating") not in (None, "") else raw.get("rating")),
        source="imdb",
    )


def download_file(url: str, dest, *, proxy: str | None = None) -> str:
    """Save ``url`` to ``dest``. Return ``saved`` or ``skipped``.

    Existing files are left untouched. Failures raise :class:`ImdbError`.
    """

    from pathlib import Path

    target = Path(dest)
    if target.exists():
        return "skipped"
    if not _http_url(url):
        raise ImdbError(f"不支持的图片地址: {url}")
    data = _get_bytes(url, _MAX_IMAGE_BYTES, proxy=proxy)
    if not data:
        raise ImdbError("图片内容为空")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return "saved"


def _choose(metas: list, query: str, year: str | None) -> dict | None:
    """Exact title only. A filename year must match. Several same titles without a year are refused."""

    wanted = normalize_title(query)
    if not wanted:
        return None
    exact: list[dict] = []
    for item in metas:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in (None, "movie"):
            continue
        imdb_id = str(item.get("imdb_id") or item.get("id") or "")
        if not _IMDB_ID_RE.fullmatch(imdb_id):
            continue
        name = normalize_title(str(item.get("name") or ""))
        if name != wanted:
            continue
        release_year = _year(item.get("releaseInfo") or item.get("year"))
        if year and release_year != year:
            continue
        exact.append(item)
    if not exact:
        return None
    if year:
        return exact[0]
    years = {_year(item.get("releaseInfo") or item.get("year")) for item in exact}
    years.discard("")
    if len(years) > 1:
        raise ImdbError(f"《{wanted}》有多部同名，文件名里没有年份，已跳过以免配错")
    return exact[0]


def _get_json(url: str, *, proxy: str | None = None) -> dict:
    raw = _get_bytes(url, _MAX_JSON_BYTES, proxy=proxy)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ImdbError(f"JSON 无法解析: {exc}") from exc
    if not isinstance(payload, dict):
        raise ImdbError("JSON 根节点不是对象")
    return payload


def _get_bytes(url: str, limit: int, *, proxy: str | None = None) -> bytes:
    from scraper.net import HttpError, fetch

    try:
        _status, data = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT_SECONDS,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, image/*, */*;q=0.1",
            },
            limit=limit,
            attempts=2,
        )
    except HttpError as exc:
        raise ImdbError(str(exc)) from exc
    return data



def _actor_photos(value) -> dict[str, str]:
    photos: dict[str, str] = {}
    if not isinstance(value, list):
        return photos
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").strip()
        url = _http_url(item.get("photo") or item.get("profile") or item.get("thumb") or item.get("image"))
        if name and url:
            photos[name] = url
    return photos


def _names(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = value.split(",") if "," in value else [value]
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("title")
                if name and str(name).strip():
                    names.append(str(name).strip())
        return names
    return []


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _http_url(value) -> str:
    text = _text(value)
    if text.lower().startswith(("http://", "https://")):
        return text
    return ""


def _year(value) -> str:
    if value is None or value == "":
        return ""
    match = _YEAR_RE.search(str(value))
    return match.group(0) if match else ""


def _date(value) -> str:
    if not value:
        return ""
    match = _DATE_RE.search(str(value))
    return match.group(1) if match else ""


def _runtime(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        minutes = int(value)
        return str(minutes) if minutes > 0 else ""
    text = str(value).strip().lower()
    match = re.search(r"(\d+)\s*min", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", text):
        return text
    return ""


def _rating(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    if isinstance(value, str):
        return value.strip()
    if float(number).is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()
