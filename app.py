#!/usr/bin/env python3
"""电影元数据刮削：桌面窗口（PySide6），以及可选命令行。

默认 ``python3 app.py`` 打开窗口。``--web`` 才启动浏览器页面。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
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
CONFIG_PATH = APP_DIR / "config.json"

SHARED_KEYS = (
    "media_dir",
    "output_dir",
    "output_mode",
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
    "uppercase_name",
    "image_naming_with_number",
    "jellyfin_mode",
    "actor_photo_kodi",
    "tpdb_token",
    "extrafanart",
    "trailer",
    "storyline",
)

GENERAL_MODE_DEFAULTS = {
    "sites": None,  # filled by default_sites("general")
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
    "uppercase_name": False,
    "image_naming_with_number": False,
    "jellyfin_mode": False,
    "actor_photo_kodi": False,
    "tpdb_token": "",
    "extrafanart": True,
    "trailer": False,
    "storyline": False,
}

OTHER_MODE_DEFAULTS = {
    "sites": None,  # filled by default_sites("other")
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
    "uppercase_name": False,
    "image_naming_with_number": False,
    "jellyfin_mode": False,
    "actor_photo_kodi": False,
    "tpdb_token": "",
    "extrafanart": True,
    "trailer": False,
    "storyline": False,
}

SHARED_DEFAULTS = {
    "media_dir": "",
    "output_dir": "",
    "output_mode": "beside",
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
    for key in ("skip_existing_nfo", "translate_plot", "download_images", "download_missing_only",
                "print_nfo", "uppercase_name", "image_naming_with_number", "jellyfin_mode",
                "actor_photo_kodi", "extrafanart", "trailer", "storyline"):
        if isinstance(raw.get(key), bool):
            data[key] = raw[key]
    for key in ("location_rule", "naming_rule", "delete_chars", "excluded_folders", "tpdb_token"):
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
    for key in ("skip_existing_nfo", "translate_plot"):
        if isinstance(raw.get(key), bool):
            mode[key] = raw[key]
    return mode


def _shared_from_raw(raw: dict) -> dict:
    data = dict(SHARED_DEFAULTS)
    if isinstance(raw.get("media_dir"), str):
        data["media_dir"] = raw["media_dir"]
    if isinstance(raw.get("output_dir"), str):
        data["output_dir"] = raw["output_dir"]
    if raw.get("output_mode") in {"beside", "folder"}:
        data["output_mode"] = raw["output_mode"]
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
    }
    return out


def load_config() -> dict:
    shared = dict(SHARED_DEFAULTS)
    general = _mode_defaults("general")
    other = _mode_defaults("other")
    film_type = "other"
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _flatten(shared, film_type, general, other)
    if not isinstance(raw, dict):
        return _flatten(shared, film_type, general, other)

    shared = _shared_from_raw(raw)
    has_nested = isinstance(raw.get("general"), dict) or isinstance(raw.get("other"), dict)
    if has_nested:
        if raw.get("film_type") in {"general", "other"}:
            film_type = raw["film_type"]
        general = _normalize_mode(raw.get("general"), "general")
        other = _normalize_mode(raw.get("other"), "other")
        # If nested missing one side but flat sites exist, ignore flat
    else:
        # Migrate flat 0.2.x into other; seed general defaults
        other = _migrate_flat_to_other(raw)
        general = _mode_defaults("general")
        film_type = "other"
        if raw.get("film_type") in {"general", "other"}:
            film_type = raw["film_type"]
    return _flatten(shared, film_type, general, other)


def _payload_from_state(shared: dict, film_type: str, general: dict, other: dict) -> dict:
    emby_type = shared.get("emby_type") if shared.get("emby_type") in {"emby", "jellyfin"} else "emby"
    avatar_source = (
        shared.get("actor_avatar_source")
        if shared.get("actor_avatar_source") in {"gfriends", "local"}
        else "gfriends"
    )
    return {
        "film_type": film_type if film_type in {"general", "other"} else "other",
        "media_dir": str(shared.get("media_dir") or ""),
        "output_dir": str(shared.get("output_dir") or ""),
        "output_mode": shared.get("output_mode") if shared.get("output_mode") in {"beside", "folder"} else "beside",
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


def save_config(data: dict) -> None:
    current = load_config()
    film_type = data.get("film_type") if data.get("film_type") in {"general", "other"} else current["film_type"]

    shared = {key: current[key] for key in SHARED_KEYS}
    for key in SHARED_KEYS:
        if key in data:
            shared[key] = data[key]

    general = copy.deepcopy(current["general"])
    other = copy.deepcopy(current["other"])

    if isinstance(data.get("general"), dict):
        merged = {**general, **data["general"]}
        general = _normalize_mode(merged, "general")
    if isinstance(data.get("other"), dict):
        merged = {**other, **data["other"]}
        other = _normalize_mode(merged, "other")

    # Flat mode-key updates apply to the active (or explicit) film_type section
    flat_mode = {key: data[key] for key in MODE_KEYS if key in data}
    if flat_mode:
        target = "general" if film_type == "general" else "other"
        if target == "general":
            general = _normalize_mode({**general, **flat_mode}, "general")
        else:
            other = _normalize_mode({**other, **flat_mode}, "other")

    # Legacy javdb/tmdb/imdb checkbox overrides
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

    payload = _payload_from_state(shared, film_type, general, other)
    CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    return merged


def run_job(settings: dict, stop_check, log, progress) -> None:
    payload = active_scrape_settings(settings)
    media = (payload.get("media_dir") or "").strip()
    mode = payload.get("output_mode") or "beside"
    output = (payload.get("output_dir") or "").strip()
    scrape(
        Path(media),
        mode=mode,
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
    mode = payload.get("output_mode") or "beside"
    output = (payload.get("output_dir") or "").strip()
    scrape_one(
        Path(video),
        mode=mode,
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
    parser.add_argument("--media", help="媒体目录")
    parser.add_argument("--output", help="移动模式下的输出目录")
    parser.add_argument(
        "--mode",
        choices=["beside", "folder"],
        help="beside=只在视频旁边写 nfo 和封面；folder=按演员/番号改名并移动到输出目录",
    )
    parser.add_argument(
        "--film-type",
        choices=["general", "other"],
        default=None,
        help="一般影片 general / 其他影片 other（默认沿用 config.json）",
    )
    parser.add_argument(
        "--imdb",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否查询 IMDb（默认沿用 config.json，否则开启）",
    )
    parser.add_argument(
        "--javdb",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否查询 JavDB（默认沿用 config.json，否则开启）",
    )
    parser.add_argument(
        "--tmdb",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否查询 TMDB（默认沿用 config.json，否则开启）",
    )
    parser.add_argument("--tmdb-key", default=None, help="TMDB API Key")
    return parser


def cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config()
    film_type = args.film_type or config.get("film_type") or "other"
    media = args.media if args.media is not None else config["media_dir"]
    output = args.output if args.output is not None else config["output_dir"]
    mode = args.mode or config["output_mode"]
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
        "output_mode": mode,
        "sites": sites,
        "tmdb_key": tmdb_key,
        "proxy": config.get("proxy") or "",
        "proxy_enabled": bool(config.get("proxy_enabled", False)),
        "skip_existing_nfo": bool(config.get("skip_existing_nfo", True)),
        "translate_plot": bool(config.get("translate_plot", True)),
        "general": config.get("general"),
        "other": config.get("other"),
    }
    # Write flat site overrides into the chosen mode section
    save_config(settings)
    label = "一般影片" if film_type == "general" else "其他影片"
    print(
        f"类型: {label}；"
        f"模式: {'旁边写 nfo/封面' if mode == 'beside' else '按演员/番号改名并移动'}；"
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
    wants_help = "--help" in argv or "-h" in argv
    wants_web = "--web" in argv
    wants_cli = "--cli" in argv or any(
        arg.startswith("--media")
        or arg.startswith("--output")
        or arg.startswith("--mode")
        or arg.startswith("--film-type")
        or arg.startswith("--imdb")
        or arg.startswith("--no-imdb")
        or arg.startswith("--javdb")
        or arg.startswith("--no-javdb")
        or arg.startswith("--tmdb")
        or arg.startswith("--no-tmdb")
        for arg in argv
    )
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
