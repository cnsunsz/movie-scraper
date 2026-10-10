#!/usr/bin/env python3
"""电影元数据刮削：桌面窗口（PySide6），以及可选命令行。

默认 ``python3 app.py`` 打开窗口。``--web`` 才启动浏览器页面。

配置：默认只用内存默认值，不会在 exe 旁自动生成 config.json。
用户通过「加载配置 / 保存 / 另存为」显式读写；CLI 可用 ``--config``。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

from scraper.organize import scrape, scrape_one
from scraper.sources import default_sites, normalize_sites


def _read_version() -> str:
    """Read VERSION next to this file, or from the PyInstaller bundle / exe dir."""
    names = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        names.append(Path(meipass) / "VERSION")
    names.append(Path(__file__).resolve().with_name("VERSION"))
    if getattr(sys, "frozen", False):
        names.append(Path(sys.executable).resolve().parent / "VERSION")
    for candidate in names:
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return "0.0.0"


__version__ = _read_version()
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

# Session-only path for the currently loaded/saved config. Never auto-created.
_config_path: Path | None = None

MAIN_MODES = ("1", "1_keep", "2", "4", "5")
LINK_MODES = ("move", "soft_link")

SHARED_KEYS = (
    "media_dir",
    "output_dir",
    "main_mode",
    "link_mode",
    "tmdb_key",
    "proxy",
    "proxy_enabled",
    "emby_type",
    "emby_url",
    "emby_api_key",
    "emby_user_id",
    "actor_avatar_source",
    "actor_local_dir",
)

MODE_KEYS = (
    "sites",
    "skip_existing_nfo",
    "translate_plot",
    "download_images",
    "download_missing_only",
    "sleep_seconds",
    "print_nfo",
    "nfo_skip_days",
    "excluded_folders",
    "excluded_size_mb",
    "location_rule",
    "naming_rule",
    "max_title_len",
    "delete_chars",
    "number_exclude_chars",
    "uppercase_name",
    "image_naming_with_number",
    "jellyfin_mode",
    "actor_photo_kodi",
    "anonymous_fill",
    "actor_only_tag",
    "tpdb_token",
    "extrafanart",
    "trailer",
    "storyline",
)

_BOOL_MODE_KEYS = (
    "skip_existing_nfo",
    "translate_plot",
    "download_images",
    "download_missing_only",
    "print_nfo",
    "uppercase_name",
    "image_naming_with_number",
    "jellyfin_mode",
    "actor_photo_kodi",
    "anonymous_fill",
    "actor_only_tag",
    "extrafanart",
    "trailer",
    "storyline",
)

_STR_MODE_KEYS = (
    "location_rule",
    "naming_rule",
    "delete_chars",
    "number_exclude_chars",
    "excluded_folders",
    "tpdb_token",
)

GENERAL_MODE_DEFAULTS = {
    "sites": None,
    "skip_existing_nfo": True,
    "translate_plot": False,
    "download_images": True,
    "download_missing_only": False,
    "sleep_seconds": 0.3,
    "print_nfo": True,
    "nfo_skip_days": 0,
    "excluded_folders": "failed,.actors",
    "excluded_size_mb": 0,
    "location_rule": "genres+'/'+title",
    "naming_rule": "title.year",
    "max_title_len": 80,
    "delete_chars": "",
    "number_exclude_chars": "",
    "uppercase_name": False,
    "image_naming_with_number": False,
    "jellyfin_mode": False,
    "actor_photo_kodi": False,
    "anonymous_fill": False,
    "actor_only_tag": False,
    "tpdb_token": "",
    "extrafanart": True,
    "trailer": False,
    "storyline": False,
}

OTHER_MODE_DEFAULTS = {
    "sites": None,
    "skip_existing_nfo": True,
    "translate_plot": True,
    "download_images": True,
    "download_missing_only": False,
    "sleep_seconds": 0.3,
    "print_nfo": True,
    "nfo_skip_days": 0,
    "excluded_folders": "failed,.actors",
    "excluded_size_mb": 0,
    "location_rule": "actor+'/'+number",
    "naming_rule": "number+'-'+title",
    "max_title_len": 80,
    "delete_chars": "",
    "number_exclude_chars": "",
    "uppercase_name": False,
    "image_naming_with_number": False,
    "jellyfin_mode": False,
    "actor_photo_kodi": False,
    "anonymous_fill": True,
    "actor_only_tag": False,
    "tpdb_token": "",
    "extrafanart": True,
    "trailer": False,
    "storyline": False,
}

SHARED_DEFAULTS = {
    "media_dir": "",
    "output_dir": "",
    "main_mode": "4",
    "link_mode": "move",
    "tmdb_key": "",
    "proxy": "",
    "proxy_enabled": False,
    "emby_type": "emby",
    "emby_url": "",
    "emby_api_key": "",
    "emby_user_id": "",
    "actor_avatar_source": "gfriends",
    "actor_local_dir": "",
}

# Flat DEFAULTS kept for older imports / docs
DEFAULTS = {
    **SHARED_DEFAULTS,
    "film_type": "other",
    "sites": None,
    "skip_existing_nfo": True,
    "translate_plot": True,
}


def get_config_path() -> Path | None:
    """Path of the config file loaded or saved this session, or None."""

    return _config_path


def set_config_path(path: Path | str | None) -> Path | None:
    """Remember the session config path (does not write). ``None`` clears it."""

    global _config_path
    if path is None or str(path).strip() == "":
        _config_path = None
        return None
    _config_path = Path(path).expanduser().resolve()
    return _config_path


def main_mode_to_output_mode(main_mode: str) -> str:
    """Map MDC main_mode to legacy beside/folder for callers that still use it."""

    if main_mode in {"1", "1_keep", "2"}:
        return "folder"
    return "beside"


def output_mode_to_main_mode(output_mode: str) -> str:
    if output_mode == "folder":
        return "1"
    return "4"


def _mode_defaults(film_type: str) -> dict:
    base = copy.deepcopy(GENERAL_MODE_DEFAULTS if film_type == "general" else OTHER_MODE_DEFAULTS)
    base["sites"] = default_sites(film_type)
    return base


def _normalize_mode(raw: dict | None, film_type: str) -> dict:
    data = _mode_defaults(film_type)
    if not isinstance(raw, dict):
        return data
    if isinstance(raw.get("sites"), list) and raw["sites"]:
        data["sites"] = normalize_sites(raw["sites"], film_type=film_type)
    for key in _BOOL_MODE_KEYS:
        if isinstance(raw.get(key), bool):
            data[key] = raw[key]
    for key in _STR_MODE_KEYS:
        if isinstance(raw.get(key), str):
            data[key] = raw[key]
    if isinstance(raw.get("sleep_seconds"), (int, float)) and float(raw["sleep_seconds"]) >= 0:
        data["sleep_seconds"] = float(raw["sleep_seconds"])
    if isinstance(raw.get("nfo_skip_days"), (int, float)) and int(raw["nfo_skip_days"]) >= 0:
        data["nfo_skip_days"] = int(raw["nfo_skip_days"])
    if isinstance(raw.get("excluded_size_mb"), (int, float)) and float(raw["excluded_size_mb"]) >= 0:
        data["excluded_size_mb"] = float(raw["excluded_size_mb"])
    if isinstance(raw.get("max_title_len"), (int, float)) and int(raw["max_title_len"]) > 0:
        data["max_title_len"] = int(raw["max_title_len"])
    return data


def _migrate_flat_to_other(raw: dict) -> dict:
    """Old 0.2.x flat config becomes the ``other`` mode profile."""

    mode = _mode_defaults("other")
    if isinstance(raw.get("sites"), list) and raw["sites"]:
        mode["sites"] = normalize_sites(raw["sites"], film_type="other")
    else:
        legacy = {
            key: raw[key]
            for key in ("javdb", "tmdb", "imdb")
            if isinstance(raw.get(key), bool)
        }
        priority = raw.get("priority") if isinstance(raw.get("priority"), str) else None
        mode["sites"] = normalize_sites(None, legacy or None, priority, film_type="other")
    for key in _BOOL_MODE_KEYS:
        if isinstance(raw.get(key), bool):
            mode[key] = raw[key]
    for key in _STR_MODE_KEYS:
        if isinstance(raw.get(key), str):
            mode[key] = raw[key]
    if isinstance(raw.get("sleep_seconds"), (int, float)) and float(raw["sleep_seconds"]) >= 0:
        mode["sleep_seconds"] = float(raw["sleep_seconds"])
    if isinstance(raw.get("nfo_skip_days"), (int, float)) and int(raw["nfo_skip_days"]) >= 0:
        mode["nfo_skip_days"] = int(raw["nfo_skip_days"])
    if isinstance(raw.get("excluded_size_mb"), (int, float)) and float(raw["excluded_size_mb"]) >= 0:
        mode["excluded_size_mb"] = float(raw["excluded_size_mb"])
    if isinstance(raw.get("max_title_len"), (int, float)) and int(raw["max_title_len"]) > 0:
        mode["max_title_len"] = int(raw["max_title_len"])
    return mode


def _shared_from_raw(raw: dict) -> dict:
    data = dict(SHARED_DEFAULTS)
    if isinstance(raw.get("media_dir"), str):
        data["media_dir"] = raw["media_dir"]
    if isinstance(raw.get("output_dir"), str):
        data["output_dir"] = raw["output_dir"]
    main_mode = raw.get("main_mode")
    if isinstance(main_mode, int):
        main_mode = str(main_mode)
    if main_mode in MAIN_MODES:
        data["main_mode"] = main_mode
    elif raw.get("output_mode") in {"beside", "folder"}:
        data["main_mode"] = output_mode_to_main_mode(raw["output_mode"])
    if raw.get("link_mode") in LINK_MODES:
        data["link_mode"] = raw["link_mode"]
    if isinstance(raw.get("proxy_enabled"), bool):
        data["proxy_enabled"] = raw["proxy_enabled"]
    for key in ("tmdb_key", "proxy", "emby_url", "emby_api_key", "emby_user_id", "actor_local_dir"):
        if isinstance(raw.get(key), str):
            data[key] = raw[key]
    if raw.get("emby_type") in {"emby", "jellyfin"}:
        data["emby_type"] = raw["emby_type"]
    if raw.get("actor_avatar_source") in {"gfriends", "local"}:
        data["actor_avatar_source"] = raw["actor_avatar_source"]
    return data


def _flatten(shared: dict, film_type: str, general: dict, other: dict) -> dict:
    active = general if film_type == "general" else other
    out = {
        **shared,
        **copy.deepcopy(active),
        "film_type": film_type,
        "general": copy.deepcopy(general),
        "other": copy.deepcopy(other),
        # Legacy alias derived from main_mode
        "output_mode": main_mode_to_output_mode(str(shared.get("main_mode") or "4")),
    }
    return out


def default_config() -> dict:
    """In-memory defaults; does not touch disk."""

    return _flatten(
        dict(SHARED_DEFAULTS),
        "other",
        _mode_defaults("general"),
        _mode_defaults("other"),
    )


def parse_config_dict(raw: dict) -> dict:
    """Validate and normalize a raw dict into the runtime config shape."""

    if not isinstance(raw, dict):
        return default_config()
    shared = _shared_from_raw(raw)
    general = _mode_defaults("general")
    other = _mode_defaults("other")
    film_type = "other"
    has_nested = isinstance(raw.get("general"), dict) or isinstance(raw.get("other"), dict)
    if has_nested:
        if raw.get("film_type") in {"general", "other"}:
            film_type = raw["film_type"]
        general = _normalize_mode(raw.get("general"), "general")
        other = _normalize_mode(raw.get("other"), "other")
    else:
        other = _migrate_flat_to_other(raw)
        general = _mode_defaults("general")
        film_type = "other"
        if raw.get("film_type") in {"general", "other"}:
            film_type = raw["film_type"]
    return _flatten(shared, film_type, general, other)


def load_config(path: Path | str | None = None) -> dict:
    """Load config from ``path``, or the session path, or return defaults.

    Never creates a file. Unknown keys are ignored. Types are validated.
    """

    target = Path(path).expanduser() if path else _config_path
    if target is None:
        return default_config()
    try:
        text = Path(target).read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return default_config()
    if not isinstance(raw, dict):
        return default_config()
    return parse_config_dict(raw)


def load_config_from(path: Path | str) -> dict:
    """Load from ``path`` and set it as the session config path on success."""

    target = Path(path).expanduser().resolve()
    try:
        text = target.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise OSError(f"无法读取配置: {exc}") from exc
    if not isinstance(raw, dict):
        raise OSError("配置文件格式无效（需要 JSON 对象）")
    parsed = parse_config_dict(raw)
    set_config_path(target)
    return parsed


def _payload_from_state(shared: dict, film_type: str, general: dict, other: dict) -> dict:
    emby_type = shared.get("emby_type") if shared.get("emby_type") in {"emby", "jellyfin"} else "emby"
    avatar_source = (
        shared.get("actor_avatar_source")
        if shared.get("actor_avatar_source") in {"gfriends", "local"}
        else "gfriends"
    )
    main_mode = shared.get("main_mode") if shared.get("main_mode") in MAIN_MODES else "4"
    link_mode = shared.get("link_mode") if shared.get("link_mode") in LINK_MODES else "move"
    return {
        "film_type": film_type if film_type in {"general", "other"} else "other",
        "media_dir": str(shared.get("media_dir") or ""),
        "output_dir": str(shared.get("output_dir") or ""),
        "main_mode": main_mode,
        "link_mode": link_mode,
        # Keep output_mode for older readers / docs
        "output_mode": main_mode_to_output_mode(main_mode),
        "tmdb_key": str(shared.get("tmdb_key") or ""),
        "proxy": str(shared.get("proxy") or ""),
        "proxy_enabled": bool(shared.get("proxy_enabled", False)),
        "emby_type": emby_type,
        "emby_url": str(shared.get("emby_url") or ""),
        "emby_api_key": str(shared.get("emby_api_key") or ""),
        "emby_user_id": str(shared.get("emby_user_id") or ""),
        "actor_avatar_source": avatar_source,
        "actor_local_dir": str(shared.get("actor_local_dir") or ""),
        "general": _normalize_mode(general, "general"),
        "other": _normalize_mode(other, "other"),
    }


def build_save_payload(data: dict) -> dict:
    """Build the on-disk JSON object from a runtime settings dict (no write)."""

    current = default_config()
    # Prefer nested blocks from data when present
    film_type = data.get("film_type") if data.get("film_type") in {"general", "other"} else current["film_type"]

    shared = {key: current[key] for key in SHARED_KEYS}
    for key in SHARED_KEYS:
        if key in data:
            shared[key] = data[key]
    # Accept legacy output_mode when main_mode absent
    if "main_mode" not in data and data.get("output_mode") in {"beside", "folder"}:
        shared["main_mode"] = output_mode_to_main_mode(data["output_mode"])
    if shared.get("main_mode") not in MAIN_MODES:
        shared["main_mode"] = "4"
    if shared.get("link_mode") not in LINK_MODES:
        shared["link_mode"] = "move"

    general = copy.deepcopy(current["general"])
    other = copy.deepcopy(current["other"])
    if isinstance(data.get("general"), dict):
        general = _normalize_mode({**general, **data["general"]}, "general")
    if isinstance(data.get("other"), dict):
        other = _normalize_mode({**other, **data["other"]}, "other")

    flat_mode = {key: data[key] for key in MODE_KEYS if key in data}
    if flat_mode:
        if film_type == "general":
            general = _normalize_mode({**general, **flat_mode}, "general")
        else:
            other = _normalize_mode({**other, **flat_mode}, "other")

    flags = {
        key: bool(data[key])
        for key in ("javdb", "tmdb", "imdb")
        if isinstance(data.get(key), bool)
    }
    if flags and "sites" not in data:
        target_sites = general["sites"] if film_type == "general" else other["sites"]
        updated = [
            {**item, "enabled": flags[item["name"]]} if item.get("name") in flags else item
            for item in target_sites
        ]
        if film_type == "general":
            general["sites"] = normalize_sites(updated, film_type="general")
        else:
            other["sites"] = normalize_sites(updated, film_type="other")

    return _payload_from_state(shared, film_type, general, other)


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically (temp file in same dir, then replace)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_config(data: dict, path: Path | str | None = None) -> Path:
    """Save ``data`` to ``path`` or the session path. Requires an explicit path.

    Does not create a default beside the exe. Updates the session path on success.
    """

    target = Path(path).expanduser().resolve() if path else _config_path
    if target is None:
        raise OSError("未指定配置路径：请先「另存为」或使用 --config")
    payload = build_save_payload(data)
    atomic_write_json(target, payload)
    set_config_path(target)
    return target


def effective_proxy(settings: dict) -> str:
    if not settings.get("proxy_enabled", False):
        return ""
    return str(settings.get("proxy") or "").strip()


def active_scrape_settings(settings: dict) -> dict:
    """Merge shared + active film_type section for scrape/run_job."""

    film_type = settings.get("film_type") if settings.get("film_type") in {"general", "other"} else "other"
    nested = settings.get(film_type)
    if isinstance(nested, dict):
        merged = {**settings, **nested, "film_type": film_type}
    else:
        merged = dict(settings)
        merged["film_type"] = film_type
    merged["proxy"] = effective_proxy(settings)
    if not isinstance(merged.get("sites"), list):
        merged["sites"] = default_sites(film_type)
    else:
        merged["sites"] = normalize_sites(merged["sites"], film_type=film_type)
    main_mode = merged.get("main_mode")
    if isinstance(main_mode, int):
        main_mode = str(main_mode)
    if main_mode not in MAIN_MODES:
        if merged.get("output_mode") in {"beside", "folder"}:
            main_mode = output_mode_to_main_mode(merged["output_mode"])
        else:
            main_mode = "4"
    merged["main_mode"] = main_mode
    merged["output_mode"] = main_mode_to_output_mode(main_mode)
    if merged.get("link_mode") not in LINK_MODES:
        merged["link_mode"] = "move"
    return merged


def run_job(settings: dict, stop_check, log, progress) -> None:
    payload = active_scrape_settings(settings)
    media = (payload.get("media_dir") or "").strip()
    output = (payload.get("output_dir") or "").strip()
    scrape(
        Path(media),
        mode=payload.get("output_mode") or "beside",
        output_dir=Path(output) if output else None,
        use_imdb=True,
        sources=payload,
        stop_check=stop_check,
        log=log,
        progress=progress,
        pause_seconds=float(payload.get("sleep_seconds") or 0),
    )


def run_one_file(settings: dict, video: Path, stop_check, log, progress) -> None:
    payload = active_scrape_settings(settings)
    output = (payload.get("output_dir") or "").strip()
    scrape_one(
        Path(video),
        mode=payload.get("output_mode") or "beside",
        output_dir=Path(output) if output else None,
        sources=payload,
        stop_check=stop_check,
        log=log,
        progress=progress,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="本地电影刮削。不带参数时打开桌面窗口；--cli 走命令行。不删除原文件。",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="使用命令行，不打开窗口",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="改用本机网页（默认是桌面窗口）",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="配置文件路径（仅读写该文件；不指定则用内存默认，不写盘）",
    )
    parser.add_argument("--media", help="媒体目录")
    parser.add_argument("--output", help="移动模式下的输出目录")
    parser.add_argument(
        "--mode",
        choices=["beside", "folder"],
        help="beside=只在视频旁边写 nfo 和封面；folder=按演员/番号改名并移动到输出目录（旧参数，等价 main_mode 4/1）",
    )
    parser.add_argument(
        "--main-mode",
        choices=list(MAIN_MODES),
        default=None,
        help="主运行模式：1 / 1_keep / 2 / 4 / 5",
    )
    parser.add_argument(
        "--film-type",
        choices=["general", "other"],
        default=None,
        help="一般影片 general / 其他影片 other（默认沿用配置或 other）",
    )
    parser.add_argument(
        "--imdb",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否查询 IMDb",
    )
    parser.add_argument(
        "--javdb",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否查询 JavDB",
    )
    parser.add_argument(
        "--tmdb",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否查询 TMDB",
    )
    parser.add_argument("--tmdb-key", default=None, help="TMDB API Key")
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="将本次 CLI 合并后的设置写回 --config 路径（需同时指定 --config）",
    )
    return parser


def cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.config:
        try:
            config = load_config_from(args.config)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            # Missing file: start from defaults but remember path if user wants --save-config
            config = default_config()
            set_config_path(Path(args.config).expanduser().resolve())
            print(f"将使用默认配置；可用 --save-config 写入 {args.config}", file=sys.stderr)
    else:
        set_config_path(None)
        config = default_config()

    film_type = args.film_type or config.get("film_type") or "other"
    media = args.media if args.media is not None else config["media_dir"]
    output = args.output if args.output is not None else config["output_dir"]
    if args.main_mode:
        main_mode = args.main_mode
    elif args.mode:
        main_mode = output_mode_to_main_mode(args.mode)
    else:
        main_mode = config.get("main_mode") or "4"
    mode = main_mode_to_output_mode(main_mode)
    sites = normalize_sites(config.get("sites"), film_type=film_type)
    overrides = {"imdb": args.imdb, "javdb": args.javdb, "tmdb": args.tmdb}
    for item in sites:
        flag = overrides.get(item["name"])
        if flag is not None:
            item["enabled"] = bool(flag)
    use_imdb = next(item["enabled"] for item in sites if item["name"] == "imdb")
    use_javdb = next(item["enabled"] for item in sites if item["name"] == "javdb")
    use_tmdb = next(item["enabled"] for item in sites if item["name"] == "tmdb")
    tmdb_key = config["tmdb_key"] if args.tmdb_key is None else args.tmdb_key
    if not media:
        print("请用 --media 指定媒体目录。", file=sys.stderr)
        parser.print_help(sys.stderr)
        return 2
    settings = {
        "film_type": film_type,
        "media_dir": media,
        "output_dir": output,
        "main_mode": main_mode,
        "output_mode": mode,
        "link_mode": config.get("link_mode") or "move",
        "sites": sites,
        "tmdb_key": tmdb_key,
        "proxy": config.get("proxy") or "",
        "proxy_enabled": bool(config.get("proxy_enabled", False)),
        "skip_existing_nfo": bool(config.get("skip_existing_nfo", True)),
        "translate_plot": bool(config.get("translate_plot", True)),
        "download_images": bool(config.get("download_images", True)),
        "download_missing_only": bool(config.get("download_missing_only", False)),
        "sleep_seconds": float(config.get("sleep_seconds") or 0.3),
        "print_nfo": bool(config.get("print_nfo", True)),
        "nfo_skip_days": int(config.get("nfo_skip_days") or 0),
        "excluded_folders": str(config.get("excluded_folders") or "failed,.actors"),
        "excluded_size_mb": float(config.get("excluded_size_mb") or 0),
        "location_rule": str(config.get("location_rule") or ""),
        "naming_rule": str(config.get("naming_rule") or ""),
        "max_title_len": int(config.get("max_title_len") or 80),
        "delete_chars": str(config.get("delete_chars") or ""),
        "number_exclude_chars": str(config.get("number_exclude_chars") or ""),
        "anonymous_fill": bool(config.get("anonymous_fill", False)),
        "actor_only_tag": bool(config.get("actor_only_tag", False)),
        "general": config.get("general"),
        "other": config.get("other"),
    }
    if args.save_config:
        if not args.config:
            print("--save-config 需要同时指定 --config 路径", file=sys.stderr)
            return 2
        try:
            save_config(settings, args.config)
            print(f"已保存配置: {args.config}", flush=True)
        except OSError as exc:
            print(f"保存配置失败: {exc}", file=sys.stderr)
            return 1
    label = "一般影片" if film_type == "general" else "其他影片"
    mode_labels = {
        "1": "整理+改名移动",
        "1_keep": "整理+保留原名移动",
        "2": "仅位置规则移动",
        "4": "原地刮削",
        "5": "原地刮削并重命名",
    }
    print(
        f"类型: {label}；"
        f"主模式: {main_mode} ({mode_labels.get(main_mode, main_mode)})；"
        f"JavDB: {'开' if use_javdb else '关'}；"
        f"TMDB: {'开' if use_tmdb else '关'}；"
        f"IMDb: {'开' if use_imdb else '关'}"
    )

    def log(message: str) -> None:
        print(message, flush=True)

    def progress(index: int, total: int, name: str) -> None:
        if total <= 0:
            print("进度: 0 / 0", flush=True)
            return
        if index <= 0:
            print(f"进度: 0 / {total}", flush=True)
            return
        print(f"进度: {index} / {total}  {name}", flush=True)

    run_job(settings, lambda: False, log, progress)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Optional env override for tests (same as --config)
    env_config = os.environ.get("MOVIE_SCRAPER_CONFIG", "").strip()
    if env_config and "--config" not in argv and not any(a.startswith("--config=") for a in argv):
        argv = ["--config", env_config, *argv]
    wants_help = "--help" in argv or "-h" in argv
    wants_web = "--web" in argv
    wants_cli = "--cli" in argv or any(
        arg.startswith("--media")
        or arg.startswith("--output")
        or arg.startswith("--mode")
        or arg.startswith("--main-mode")
        or arg.startswith("--film-type")
        or arg.startswith("--imdb")
        or arg.startswith("--no-imdb")
        or arg.startswith("--javdb")
        or arg.startswith("--no-javdb")
        or arg.startswith("--tmdb")
        or arg.startswith("--no-tmdb")
        or arg.startswith("--config")
        or arg == "--save-config"
        for arg in argv
    )
    # Pre-set session path from --config for GUI too
    config_arg = None
    for index, arg in enumerate(argv):
        if arg == "--config" and index + 1 < len(argv):
            config_arg = argv[index + 1]
            break
        if arg.startswith("--config="):
            config_arg = arg.split("=", 1)[1]
            break
    if config_arg and not wants_cli:
        try:
            load_config_from(config_arg)
        except OSError:
            set_config_path(Path(config_arg).expanduser().resolve())
    if wants_web and not wants_cli and not wants_help:
        from webui import serve
        return serve()
    if wants_cli or wants_help:
        cleaned = [arg for arg in argv if arg not in {"--cli", "--web"}]
        return cli(cleaned)
    try:
        from ui import launch
    except ImportError as exc:
        print("无法加载桌面界面。请先安装依赖: python3 -m pip install -r requirements.txt", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1
    return launch()


if __name__ == "__main__":
    sys.exit(main())
