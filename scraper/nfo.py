"""Write a Kodi / Emby / Jellyfin movie NFO in the MDC field layout."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from scraper.imdb import MovieMetadata


def render_nfo(
    meta: MovieMetadata,
    *,
    artwork: dict[str, bool] | None = None,
    actor_files: dict[str, str] | None = None,
) -> str:
    """UTF-8 movie XML. Title and plot use CDATA. Text is escaped."""

    flags = artwork or {}
    lines = ['<?xml version="1.0" encoding="UTF-8" ?>', "<movie>"]

    def cdata(tag: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        safe = cleaned.replace("]]>", "]]]]><![CDATA[>")
        lines.append(f"  <{tag}><![CDATA[{safe}]]></{tag}>")

    def plain(tag: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        lines.append(f"  <{tag}>{escape(cleaned)}</{tag}>")

    cdata("title", meta.title)
    cdata("originaltitle", meta.original_title or meta.title)
    cdata("sorttitle", meta.code or meta.title)
    if meta.code or meta.source == "javdb":
        plain("customrating", "JP-18+")
        plain("mpaa", "JP-18+")
    if meta.series:
        lines.append("  <set>")
        lines.append(f"    <name>{escape(meta.series.strip())}</name>")
        lines.append("  </set>")
    plain("studio", meta.studio)
    plain("year", meta.year)
    cdata("outline", meta.plot)
    cdata("plot", meta.plot)
    plain("runtime", meta.runtime)
    if flags.get("poster", True) and (meta.poster_url or flags.get("poster")):
        plain("poster", "poster.jpg")
    if flags.get("thumb", flags.get("poster", False)):
        plain("thumb", "thumb.jpg")
    if flags.get("fanart"):
        plain("fanart", "fanart.jpg")
    portraits = actor_files or {}
    for name in meta.cast:
        cleaned = (name or "").strip()
        if not cleaned:
            continue
        lines.append("  <actor>")
        lines.append(f"    <name>{escape(cleaned)}</name>")
        thumb = portraits.get(cleaned) or portraits.get(name) or ""
        if thumb:
            lines.append(f"    <thumb>{escape(thumb)}</thumb>")
        lines.append("  </actor>")
    plain("maker", meta.studio)
    plain("label", meta.label or meta.studio)
    seen: list[str] = []
    for value in list(meta.tags) + list(meta.genres):
        cleaned = (value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.append(cleaned)
        plain("tag", cleaned)
        plain("genre", cleaned)
    plain("num", meta.code)
    date = meta.premiered
    plain("premiered", date)
    plain("releasedate", date)
    plain("release", date)
    plain("rating", meta.rating)
    if meta.source in {"javdb", "javbus", "tmdb", "imdb", "dmm", "avsox", "mgstage", "fc2"}:
        plain("source", meta.source)
    identities: list[tuple[str, str]] = []
    if (meta.imdb_id or "").strip():
        identities.append(("imdb", meta.imdb_id.strip()))
    if (meta.tmdb_id or "").strip():
        identities.append(("tmdb", meta.tmdb_id.strip()))
    if (meta.javdb_id or "").strip():
        identities.append(("javdb", meta.javdb_id.strip()))
    for index, (kind, value) in enumerate(identities):
        default = ' default="true"' if index == 0 else ""
        lines.append(f'  <uniqueid type="{kind}"{default}>{escape(value)}</uniqueid>')
    for director in meta.directors:
        plain("director", director)
    lines.append("</movie>")
    return "\n".join(lines) + "\n"


def write_nfo(
    path: Path,
    meta: MovieMetadata,
    *,
    artwork: dict[str, bool] | None = None,
    actor_files: dict[str, str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_nfo(meta, artwork=artwork, actor_files=actor_files), encoding="utf-8")
