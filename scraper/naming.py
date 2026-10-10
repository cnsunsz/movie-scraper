"""Safe folder / file naming rules (no eval).

Supports MDC-style expressions:

* Plus/quotes: ``actor+'/'+title``, ``number+"-"+title``
* Dot shorthand: ``title.year``
* Slash/dash shorthand: ``genres/title``, ``actor/[number]-title``, ``actor/number``

Tokens: title, original_title, actor, studio, director, release, year,
number, tag, genres, outline (skipped in path segments), runtime, series,
prefix, letter, season, episode, suffix.
"""

from __future__ import annotations

import re
from typing import Mapping

from scraper.imdb import MovieMetadata

_TOKENS = frozenset({
    "title",
    "original_title",
    "actor",
    "studio",
    "director",
    "release",
    "year",
    "number",
    "tag",
    "genres",
    "outline",
    "runtime",
    "series",
    "prefix",
    "letter",
    "season",
    "episode",
    "suffix",
})
# Longer names first so original_title matches before title
_TOKEN_WORD = re.compile(
    r"(?i)(original_title|outline|runtime|director|release|episode|"
    r"series|studio|prefix|letter|season|suffix|number|genres|"
    r"actor|title|year|tag)"
)
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_PATH_SKIP = frozenset({"outline"})


def rule_values(meta: MovieMetadata, *, suffix: str = "") -> dict[str, str]:
    """Map rule tokens to fragments from metadata (unsanitized)."""

    actor = ""
    if meta.cast:
        actor = str(meta.cast[0] or "").strip()
        if actor in {"未知", "unknown", "Unknown"}:
            actor = ""
    genres = ""
    if meta.genres:
        genres = str(meta.genres[0] or "").strip()
    if not genres and meta.tags:
        genres = str(meta.tags[0] or "").strip()
    tag = genres
    if meta.tags:
        tag = str(meta.tags[0] or "").strip() or tag
    number = str(meta.code or "").strip()
    prefix = ""
    letter = ""
    if number:
        if "-" in number:
            prefix = number.split("-", 1)[0]
        else:
            match = re.match(r"^([A-Za-z]+)", number)
            prefix = match.group(1) if match else number[:1]
        letter = (prefix or number)[:1].upper()
    director = ""
    if meta.directors:
        director = str(meta.directors[0] or "").strip()
    release = str(meta.premiered or "").strip()
    ext = (suffix or "").lstrip(".")
    return {
        "title": str(meta.title or "").strip(),
        "original_title": str(meta.original_title or meta.title or "").strip(),
        "actor": actor,
        "studio": str(meta.studio or "").strip(),
        "director": director,
        "release": release,
        "year": str(meta.year or "").strip(),
        "number": number,
        "tag": tag,
        "genres": genres,
        "outline": str(meta.plot or "").strip(),
        "runtime": str(meta.runtime or "").strip(),
        "series": str(meta.series or "").strip(),
        "prefix": prefix,
        "letter": letter,
        "season": str(getattr(meta, "season", "") or "").strip(),
        "episode": str(getattr(meta, "episode", "") or "").strip(),
        "suffix": ext,
    }


def eval_rule(rule: str, values: Mapping[str, str], *, default: str = "未知") -> str:
    """Evaluate a naming / location rule without ``eval``.

    Path separators (``/``) in the result are kept for folder location rules;
    each path segment is sanitized separately. ``outline`` is dropped from
    path segments so long plots never become folder names.
    """

    text = (rule or "").strip()
    if not text:
        return default
    # Leading # is an MDC-style hint; ignore for evaluation
    if text.startswith("#"):
        text = text[1:].lstrip()
    try:
        pieces = _parse_pieces(text, values)
    except ValueError:
        return default
    if not pieces:
        return default
    result = "".join(pieces)
    if "/" in result:
        parts = []
        for part in result.split("/"):
            cleaned = _clean_segment(part)
            if cleaned:
                parts.append(cleaned)
        return "/".join(parts) if parts else default
    return _clean_segment(result) or default


def apply_delete_chars(text: str, delete_chars: str) -> str:
    if not delete_chars:
        return text
    table = str.maketrans("", "", delete_chars)
    return text.translate(table)


def truncate_title(text: str, max_len: int) -> str:
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[:max_len].rstrip(" .-")


def _parse_pieces(text: str, values: Mapping[str, str]) -> list[str]:
    """Split plus/quote rules or shorthand path/name rules into string pieces."""

    if "+" in text or "'" in text or '"' in text:
        return _parse_plus_pieces(text, values)
    return [_resolve_shorthand(text, values)]


def _parse_plus_pieces(text: str, values: Mapping[str, str]) -> list[str]:
    pieces: list[str] = []
    i = 0
    n = len(text)
    expect_operand = True
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if not expect_operand:
            if text[i] == "+":
                i += 1
                expect_operand = True
                continue
            raise ValueError("expected +")
        ch = text[i]
        if ch in {"'", '"'}:
            quote = ch
            i += 1
            start = i
            while i < n and text[i] != quote:
                i += 1
            if i >= n:
                raise ValueError("unclosed quote")
            pieces.append(text[start:i])
            i += 1
        else:
            match = _TOKEN_WORD.match(text, i)
            if not match:
                raise ValueError("expected token or literal")
            names = [match.group(1).lower()]
            i = match.end()
            while i < n and text[i] == ".":
                nxt = _TOKEN_WORD.match(text, i + 1)
                if not nxt:
                    raise ValueError("bad dotted token")
                names.append(nxt.group(1).lower())
                i = nxt.end()
            pieces.append(_join_token_values(names, values))
        expect_operand = False
    if expect_operand and pieces:
        raise ValueError("trailing +")
    if expect_operand and not pieces:
        raise ValueError("empty")
    return pieces


def _resolve_shorthand(text: str, values: Mapping[str, str]) -> str:
    """Parse ``genres/title``, ``actor/[number]-title``, ``title.year``."""

    text = text.strip()
    if not text:
        return ""
    # Pure dotted tokens (no / - [ ])
    if re.fullmatch(r"[A-Za-z_.]+", text) and "." in text:
        names = [part.lower() for part in text.split(".")]
        if all(name in _TOKENS for name in names):
            return _join_token_values(names, values)
    if text.lower() in _TOKENS:
        return _token_value(text.lower(), values)

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "[":
            close = text.find("]", i + 1)
            if close < 0:
                raise ValueError("unclosed [")
            inner = text[i + 1 : close].strip().lower()
            if inner not in _TOKENS:
                raise ValueError("bad bracket token")
            out.append("[")
            out.append(_token_value(inner, values))
            out.append("]")
            i = close + 1
            continue
        if text[i] == "/":
            out.append("/")
            i += 1
            continue
        match = _TOKEN_WORD.match(text, i)
        if match:
            name = match.group(1).lower()
            out.append(_token_value(name, values))
            i = match.end()
            continue
        # Literal punctuation / separators kept as-is (e.g. - . _)
        out.append(text[i])
        i += 1
    return "".join(out)


def _token_value(name: str, values: Mapping[str, str]) -> str:
    if name in _PATH_SKIP:
        return ""
    return str(values.get(name, "") or "")


def _join_token_values(names: list[str], values: Mapping[str, str]) -> str:
    parts = [_token_value(name, values) for name in names]
    if len(parts) == 1:
        return parts[0]
    return ".".join(part for part in parts if part)


def _clean_segment(text: str) -> str:
    text = _INVALID.sub(" ", text or "").strip()
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text
