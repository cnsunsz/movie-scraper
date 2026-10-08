"""Parse a video filename into an IMDb id, a studio code, and a search title.

This is original logic for a local library tool. It does not come from
Movie Data Capture / MDCx.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

VIDEO_EXTENSIONS = {
    "mkv",
    "mp4",
    "avi",
    "wmv",
    "ts",
    "m2ts",
    "iso",
    "rmvb",
    "flv",
    "mov",
}

_FLAGS = re.IGNORECASE | re.ASCII

_IMDB_RE = re.compile(r"(?<![a-z0-9])(tt\d{7,8})(?!\d)", _FLAGS)
_FC2_PPV_RE = re.compile(
    r"(?<![a-z0-9])fc2[-_\s]?ppv[-_\s]?(\d{5,7})(?!\d)", _FLAGS
)
_FC2_RE = re.compile(r"(?<![a-z0-9])fc2[-_\s]?(\d{5,7})(?!\d)", _FLAGS)
_HEYZO_RE = re.compile(r"(?<![a-z0-9])heyzo[-_\s]?(\d{3,5})(?!\d)", _FLAGS)
_TOKYO_RE = re.compile(
    r"(?<![a-z0-9])tokyo[-_\s]?hot[-_\s]?n(\d{3,5})(?!\d)", _FLAGS
)
_N_RE = re.compile(r"(?<![a-z0-9])n(\d{4})(?!\d)", _FLAGS)
_STD_RE = re.compile(r"(?<![a-z0-9])([a-z]{2,10})[-_](\d{2,5})(?!\d)", _FLAGS)
_GLUED_RE = re.compile(r"(?<![a-z0-9])([a-z]{2,10})(0\d{2,5})(?!\d)", _FLAGS)

_YEAR_RE = re.compile(r"(?:19|20)\d{2}", _FLAGS)
_CD_RE = re.compile(r"(?:cd|part)\d+", _FLAGS)
_C_TAG_RE = re.compile(
    r"[-._]c(?=$|[-._](?![a-z](?:[-._]|$)))", _FLAGS
)

# Whole tokens dropped before a title search. "c" is handled separately so
# dotted abbreviations (C.R.A.Z.Y) are not eaten.
_JUNK = {
    "1080p",
    "2160p",
    "4k",
    "x264",
    "x265",
    "hevc",
    "bluray",
    "blu-ray",
    "web-dl",
    "webdl",
    "webrip",
}
_SKIP_LETTERS = {"cd", "part", "disc"}


@dataclass(frozen=True)
class ParsedName:
    """What we could read from a filename without touching the network."""

    imdb_id: str | None
    code: str | None
    title: str
    year: str | None


def parse_filename(filename: str) -> ParsedName:
    """Parse ``filename`` (a path or a bare name).

    Order: IMDb id ``tt`` + 7 or 8 digits, then a studio code, otherwise the
    cleaned stem is the title. A trailing ``-cd1`` / ``-part1`` is not part
    of the code.
    """

    base = os.path.basename(str(filename).replace("\\", "/"))
    stem = _strip_video_ext(base)

    imdb_id = None
    imdb_span = None
    imdb_match = _IMDB_RE.search(stem)
    if imdb_match:
        imdb_id = imdb_match.group(1).lower()
        imdb_span = imdb_match.span(1)

    code, code_span = _find_code(stem, imdb_span)

    chars = list(stem)
    for span in (imdb_span, code_span):
        if not span:
            continue
        for index in range(span[0], span[1]):
            chars[index] = " "
    title, year = _clean_title("".join(chars))
    return ParsedName(imdb_id=imdb_id, code=code, title=title, year=year)


def _strip_video_ext(base: str) -> str:
    stem, ext = os.path.splitext(base)
    if ext.lower().lstrip(".") in VIDEO_EXTENSIONS:
        return stem
    return base


def _overlaps(span: tuple[int, int], blocked: tuple[int, int] | None) -> bool:
    if not blocked:
        return False
    return not (span[1] <= blocked[0] or span[0] >= blocked[1])


def _find_code(
    stem: str, blocked: tuple[int, int] | None
) -> tuple[str | None, tuple[int, int] | None]:
    """Return ``(normalized code, span in stem)`` or ``(None, None)``."""

    steps = (
        ("fc2ppv", _FC2_PPV_RE),
        ("fc2", _FC2_RE),
        ("heyzo", _HEYZO_RE),
        ("tokyo", _TOKYO_RE),
        ("n", _N_RE),
        ("std", _STD_RE),
        ("glued", _GLUED_RE),
    )
    for kind, pattern in steps:
        for match in pattern.finditer(stem):
            if _overlaps(match.span(), blocked):
                continue
            code = _format_code(kind, match)
            if code:
                return code, match.span()
    return None, None


def _format_code(kind: str, match: re.Match[str]) -> str | None:
    if kind == "fc2ppv":
        return f"FC2-PPV-{match.group(1)}"
    if kind == "fc2":
        return f"FC2-{match.group(1)}"
    if kind == "heyzo":
        return f"HEYZO-{match.group(1)}"
    if kind == "tokyo":
        return f"n{match.group(1)}"
    if kind == "n":
        return f"n{match.group(1)}"
    if kind == "std":
        letters, digits = match.group(1), match.group(2)
        if letters.lower() in _SKIP_LETTERS or _looks_like_title(letters, digits):
            return None
        return f"{letters.upper()}-{digits}"
    if kind == "glued":
        letters, digits = match.group(1), match.group(2)
        if letters.lower() in _SKIP_LETTERS or _looks_like_title(letters, digits):
            return None
        return f"{letters.upper()}-{_normalize_padded(digits)}"
    return None


def _looks_like_title(letters: str, digits: str) -> bool:
    """Avoid treating ``Inception-2010`` / ``Knight-2008`` as a studio code.

    A long letter run plus a calendar year is almost always a title. Short
    codes such as ``SSNI-2010`` (4 letters) are kept.
    """

    normalized = digits.lstrip("0") or "0"
    if len(letters) >= 6 and (
        _YEAR_RE.fullmatch(digits) or _YEAR_RE.fullmatch(normalized)
    ):
        return True
    return False


def _normalize_padded(num: str) -> str:
    """Drop leading zeros, but keep at least 3 digits when the source was padded."""

    stripped = num.lstrip("0") or "0"
    if len(stripped) < 3:
        return stripped.zfill(3)
    return stripped


def _clean_title(text: str) -> tuple[str, str | None]:
    text = text.replace("\u3000", " ")
    text = text.replace("中字幕", " ")
    previous = None
    while previous != text:
        previous = text
        text = _C_TAG_RE.sub(" ", text)
    for bracket in "[]【】()（）":
        text = text.replace(bracket, " ")
    text = re.sub(r"[._]+", " ", text)
    raw_tokens = [piece for piece in re.split(r"\s+", text.strip()) if piece]
    tokens: list[str] = []
    for token in raw_tokens:
        parts = [part for part in token.split("-") if part]
        if len(parts) > 1 and any(_splits_hyphen(part) for part in parts):
            tokens.extend(parts)
        else:
            tokens.append(token.strip("-"))
    kept = [token for token in tokens if token and not _is_junk(token)]
    title = re.sub(r"\s+", " ", " ".join(kept)).strip()
    years = _YEAR_RE.findall(title)
    year = years[-1] if years else None
    return title, year


def _splits_hyphen(part: str) -> bool:
    return _is_junk(part) or bool(_YEAR_RE.fullmatch(part))


def _is_junk(token: str) -> bool:
    lowered = token.lower()
    if lowered in _JUNK:
        return True
    if _CD_RE.fullmatch(token):
        return True
    return False
