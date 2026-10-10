"""Safe folder / file naming rules (no eval).

Supports expressions like ``actor+'/'+title``, ``number+"-"+title``,
``genres+'/'+title``, and the shorthand ``title.year``.
Tokens: actor, title, genres, number, year.
"""

from __future__ import annotations

import re
from typing import Mapping

from scraper.imdb import MovieMetadata

_TOKENS = frozenset({"actor", "title", "genres", "number", "year"})
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_TOKEN_WORD = re.compile(r"(?i)(actor|title|genres|number|year)")


def rule_values(meta: MovieMetadata) -> dict[str, str]:
    """Map rule tokens to fragments from metadata (unsanitized)."""

    actor = ""
    if meta.cast:
        actor = str(meta.cast[0] or "").strip()
        if actor in {"未知", "unknown", "Unknown"}:
            actor = ""
    genres = ""
    if meta.genres:
        genres = str(meta.genres[0] or "").strip()
    return {
        "actor": actor,
        "title": str(meta.title or "").strip(),
        "genres": genres,
        "number": str(meta.code or "").strip(),
        "year": str(meta.year or "").strip(),
    }


def eval_rule(rule: str, values: Mapping[str, str], *, default: str = "未知") -> str:
    """Evaluate a naming / location rule without ``eval``.

    Path separators (``/``) in the result are kept for folder location rules;
    each path segment is sanitized separately.
    """

    text = (rule or "").strip()
    if not text:
        return default
    try:
        pieces = _parse_pieces(text, values)
    except ValueError:
        return default
    if not pieces:
        return default
    result = "".join(pieces)
    if "/" in result:
        parts = [_clean_segment(part) for part in result.split("/")]
        parts = [part for part in parts if part]
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
    """Split ``a + '/' + b`` or ``title.year`` into string pieces."""

    # Fast path: only dotted tokens, no quotes / plus
    if "+" not in text and "'" not in text and '"' not in text:
        return [_resolve_dotted(text, values)]

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


def _resolve_dotted(text: str, values: Mapping[str, str]) -> str:
    text = text.strip()
    if not text:
        return ""
    names = [part.lower() for part in text.split(".")]
    if not all(name in _TOKENS for name in names):
        raise ValueError("unknown token")
    return _join_token_values(names, values)


def _join_token_values(names: list[str], values: Mapping[str, str]) -> str:
    parts = [str(values.get(name, "") or "") for name in names]
    if len(parts) == 1:
        return parts[0]
    return ".".join(part for part in parts if part)


def _clean_segment(text: str) -> str:
    text = _INVALID.sub(" ", text or "").strip()
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text
