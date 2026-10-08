"""Optional TMDB lookup. Needs the user's own free API key.

* ``GET /find/{imdb}?external_source=imdb_id``
* ``GET /search/movie``
* ``GET /movie/{id}?append_to_response=credits,external_ids``

Language is ``zh-CN``. Images use the public image CDN.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from scraper.imdb import MovieMetadata
from scraper.match import normalize_title
from scraper.net import HttpError, fetch

API = "https://api.themoviedb.org/3"
TIMEOUT = 20
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


class TmdbError(Exception):
    """TMDB rejected the key or the request failed."""


def lookup(
    *,
    api_key: str,
    imdb_id: str | None = None,
    title: str | None = None,
    year: str | None = None,
    proxy: str | None = None,
) -> MovieMetadata | None:
    key = (api_key or "").strip()
    if not key:
        raise TmdbError("TMDB 已勾选但没有 API Key，已跳过")
    movie_id = None
    if imdb_id:
        movie_id = _find_imdb(imdb_id, key, proxy)
    if movie_id is None:
        query = (title or "").strip()
        if not query:
            return None
        movie_id = _search(query, year, key, proxy)
    if movie_id is None:
        return None
    return _details(movie_id, key, proxy)


def _find_imdb(imdb_id: str, api_key: str, proxy: str | None) -> int | None:
    payload = _get(
        f"/find/{urllib.parse.quote(imdb_id)}",
        api_key,
        proxy,
        external_source="imdb_id",
    )
    results = payload.get("movie_results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if isinstance(first, dict) and first.get("id"):
        return int(first["id"])
    return None


def _search(query: str, year: str | None, api_key: str, proxy: str | None) -> int | None:
    params = {"query": query}
    if year and _YEAR_RE.fullmatch(year):
        params["year"] = year
    payload = _get("/search/movie", api_key, proxy, **params)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None
    chosen = _pick(results, query, year)
    if not chosen or not chosen.get("id"):
        return None
    return int(chosen["id"])


def _details(movie_id: int, api_key: str, proxy: str | None) -> MovieMetadata | None:
    payload = _get(
        f"/movie/{movie_id}",
        api_key,
        proxy,
        append_to_response="credits,external_ids",
    )
    if not isinstance(payload, dict) or not (payload.get("title") or payload.get("name")):
        return None
    collection = payload.get("belongs_to_collection")
    series = ""
    if isinstance(collection, dict) and collection.get("name"):
        series = str(collection["name"]).strip()
    title = str(payload.get("title") or "").strip()
    original = str(payload.get("original_title") or title).strip()
    premiered = str(payload.get("release_date") or "").strip()
    year = premiered[:4] if len(premiered) >= 4 and premiered[:4].isdigit() else ""
    runtime = payload.get("runtime")
    runtime_text = str(int(runtime)) if isinstance(runtime, (int, float)) and runtime else ""
    genres = [
        str(item.get("name")).strip()
        for item in payload.get("genres") or []
        if isinstance(item, dict) and item.get("name")
    ]
    credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else {}
    directors = []
    for person in credits.get("crew") or []:
        if isinstance(person, dict) and person.get("job") == "Director" and person.get("name"):
            directors.append(str(person["name"]).strip())
    cast = []
    photos: dict[str, str] = {}
    for person in credits.get("cast") or []:
        if isinstance(person, dict) and person.get("name"):
            name = str(person["name"]).strip()
            cast.append(name)
            photo = _image(person.get("profile_path"), "w185")
            if photo:
                photos[name] = photo
        if len(cast) >= 20:
            break
    external = payload.get("external_ids") if isinstance(payload.get("external_ids"), dict) else {}
    imdb_id = str(external.get("imdb_id") or "").strip().lower()
    if not re.fullmatch(r"tt\d{7,8}", imdb_id):
        imdb_id = ""
    vote = payload.get("vote_average")
    rating = ""
    if isinstance(vote, (int, float)) and vote > 0:
        rating = f"{float(vote):.1f}".rstrip("0").rstrip(".")
    return MovieMetadata(
        title=title,
        original_title=original or title,
        year=year,
        premiered=premiered if re.fullmatch(r"\d{4}-\d{2}-\d{2}", premiered) else "",
        plot=str(payload.get("overview") or "").strip(),
        runtime=runtime_text,
        genres=genres,
        directors=directors,
        cast=cast,
        actor_photos=photos,
        poster_url=_image(payload.get("poster_path"), "w780"),
        fanart_url=_image(payload.get("backdrop_path"), "w1280"),
        imdb_id=imdb_id,
        tmdb_id=str(payload.get("id") or movie_id),
        rating=rating,
        source="tmdb",
        series=series,
        studio=_studio(payload.get("production_companies")),
    )


def _pick(results: list, query: str, year: str | None) -> dict | None:
    """Exact title only. Filename year must match. Several years and no filename year is a skip."""

    wanted = normalize_title(query)
    if not wanted:
        return None
    exact: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        names = {
            normalize_title(str(item.get("title") or "")),
            normalize_title(str(item.get("original_title") or "")),
        }
        names.discard("")
        if wanted not in names:
            continue
        release_year = str(item.get("release_date") or "")[:4]
        if not release_year.isdigit():
            release_year = ""
        if year and release_year != year:
            continue
        exact.append(item)
    if not exact:
        return None
    if not year:
        years = set()
        for item in exact:
            release_year = str(item.get("release_date") or "")[:4]
            if release_year.isdigit():
                years.add(release_year)
        if len(years) > 1:
            raise TmdbError("有多部同名，文件名里没有年份")
    return exact[0]


def _studio(companies) -> str:
    if not isinstance(companies, list):
        return ""
    for item in companies:
        if isinstance(item, dict) and item.get("name"):
            return str(item["name"]).strip()
    return ""


def _image(path: object, size: str) -> str:
    text = str(path or "").strip()
    if not text or text == "None":
        return ""
    if not text.startswith("/"):
        text = "/" + text
    return f"https://image.tmdb.org/t/p/{size}{text}"


def _get(path: str, api_key: str, proxy: str | None, **params: str) -> dict:
    query = {"api_key": api_key, "language": "zh-CN"}
    query.update({key: value for key, value in params.items() if value is not None})
    url = API + path + "?" + urllib.parse.urlencode(query)
    try:
        status, body = fetch(
            url,
            proxy=proxy,
            timeout=TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "MovieScraper/1.0"},
            limit=2_000_000,
            attempts=2,
        )
    except HttpError as exc:
        if exc.status in {401, 403}:
            raise TmdbError("TMDB 拒绝了 API Key") from exc
        raise TmdbError(f"TMDB 请求失败: {exc}") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TmdbError(f"TMDB JSON 无法解析: {exc}") from exc
    if isinstance(payload, dict) and payload.get("success") is False:
        message = str(payload.get("status_message") or "TMDB 返回错误")
        raise TmdbError(message)
    if status >= 400:
        raise TmdbError(f"TMDB HTTP {status}")
    if not isinstance(payload, dict):
        raise TmdbError("TMDB 响应不是对象")
    return payload
