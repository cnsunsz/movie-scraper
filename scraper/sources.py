"""Which metadata sites to try, and in what order."""

from __future__ import annotations

SOURCE_NAMES = (
    "javdb",
    "javbus",
    "tmdb",
    "imdb",
    "dmm",
    "avsox",
    "mgstage",
    "fc2",
)
CODE_SITES = ("javdb", "javbus", "dmm", "avsox", "mgstage", "fc2")
TITLE_SITES = ("tmdb", "imdb")
DEFAULT_PRIORITY = "javdb,javbus,tmdb,imdb,dmm,avsox,mgstage,fc2"

SITE_LABELS = {
    "javdb": "JavDB",
    "javbus": "JavBus",
    "tmdb": "TMDB",
    "imdb": "IMDb",
    "dmm": "DMM",
    "avsox": "AVSOX",
    "mgstage": "MGStage",
    "fc2": "FC2",
}

# 「其他影片」：番号站优先（与 0.2.x 默认一致）
DEFAULT_ENABLED_OTHER = {
    "javdb": True,
    "javbus": True,
    "tmdb": True,
    "imdb": True,
    "dmm": False,
    "avsox": False,
    "mgstage": False,
    "fc2": False,
}
DEFAULT_ORDER_OTHER = (
    "javdb",
    "javbus",
    "tmdb",
    "imdb",
    "dmm",
    "avsox",
    "mgstage",
    "fc2",
)

# 「一般影片」：TMDB / IMDb 优先，番号站默认关闭
DEFAULT_ENABLED_GENERAL = {
    "javdb": False,
    "javbus": False,
    "tmdb": True,
    "imdb": True,
    "dmm": False,
    "avsox": False,
    "mgstage": False,
    "fc2": False,
}
DEFAULT_ORDER_GENERAL = (
    "tmdb",
    "imdb",
    "javdb",
    "javbus",
    "dmm",
    "avsox",
    "mgstage",
    "fc2",
)

# 兼容旧名
DEFAULT_ENABLED = DEFAULT_ENABLED_OTHER


def default_sites(film_type: str = "other") -> list[dict]:
    if film_type == "general":
        order, enabled = DEFAULT_ORDER_GENERAL, DEFAULT_ENABLED_GENERAL
    else:
        order, enabled = DEFAULT_ORDER_OTHER, DEFAULT_ENABLED_OTHER
    return [{"name": name, "enabled": bool(enabled[name])} for name in order]


def normalize_sites(
    value,
    legacy_enabled: dict | None = None,
    legacy_priority: str | None = None,
    *,
    film_type: str = "other",
) -> list[dict]:
    """Ordered ``{name, enabled}`` list. Old priority text and checkboxes migrate in."""

    base = default_sites(film_type)
    enabled = {item["name"]: item["enabled"] for item in base}
    if legacy_enabled:
        for name, flag in legacy_enabled.items():
            if name in enabled:
                enabled[name] = bool(flag)
    order: list[str] = []
    if isinstance(value, list) and value:
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            if name not in enabled or name in order:
                continue
            order.append(name)
            if "enabled" in item:
                enabled[name] = bool(item.get("enabled"))
    elif legacy_priority:
        for token in legacy_priority.split(","):
            name = token.strip().lower()
            if name in enabled and name not in order:
                order.append(name)
    for name in (item["name"] for item in base):
        if name not in order:
            order.append(name)
    for name in SOURCE_NAMES:
        if name not in order:
            order.append(name)
    return [{"name": name, "enabled": bool(enabled[name])} for name in order]


def enabled_names(sites: list[dict] | None) -> list[str]:
    names = []
    for item in sites or []:
        if isinstance(item, dict) and item.get("name") in SITE_LABELS and item.get("enabled"):
            name = str(item["name"])
            if name not in names:
                names.append(name)
    return names


def resolve_priority(text: str | None, enabled: dict[str, bool]) -> list[str]:
    """Enabled sources in the order written in ``text``.

    Unknown tokens and duplicates are ignored. A source that is turned off
    is skipped even if it appears in the text. A blank text uses the default
    order. Missing keys count as off, so older callers that only name three
    sites keep their old result.
    """

    raw = (text or "").strip() or DEFAULT_PRIORITY
    order: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower()
        if name not in SOURCE_NAMES:
            continue
        if not enabled.get(name):
            continue
        if name in order:
            continue
        order.append(name)
    return order
