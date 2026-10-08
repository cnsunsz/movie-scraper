#!/usr/bin/env python3
"""电影元数据刮削：桌面窗口（PySide6），以及可选命令行。

默认 ``python3 app.py`` 打开窗口。``--web`` 才启动浏览器页面。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scraper.organize import scrape
from scraper.sources import normalize_sites

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS = {
    "media_dir": "",
    "output_dir": "",
    "output_mode": "beside",
    "sites": None,
    "tmdb_key": "",
    "proxy": "",
    "skip_existing_nfo": True,
    "translate_plot": True,
}


def load_config() -> dict:
    data = dict(DEFAULTS)
    data["sites"] = normalize_sites(None)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return data
    if not isinstance(raw, dict):
        return data
    if isinstance(raw.get("media_dir"), str):
        data["media_dir"] = raw["media_dir"]
    if isinstance(raw.get("output_dir"), str):
        data["output_dir"] = raw["output_dir"]
    if raw.get("output_mode") in {"beside", "folder"}:
        data["output_mode"] = raw["output_mode"]
    for key in ("skip_existing_nfo", "translate_plot"):
        if isinstance(raw.get(key), bool):
            data[key] = raw[key]
    for key in ("tmdb_key", "proxy"):
        if isinstance(raw.get(key), str):
            data[key] = raw[key]
    if isinstance(raw.get("sites"), list) and raw["sites"]:
        data["sites"] = normalize_sites(raw["sites"])
    else:
        legacy = {
            key: raw[key]
            for key in ("javdb", "tmdb", "imdb")
            if isinstance(raw.get(key), bool)
        }
        priority = raw.get("priority") if isinstance(raw.get("priority"), str) else None
        data["sites"] = normalize_sites(None, legacy or None, priority)
    return data


def save_config(data: dict) -> None:
    current = load_config()
    current.update(data)
    if "sites" not in data:
        flags = {
            key: bool(data[key])
            for key in ("javdb", "tmdb", "imdb")
            if isinstance(data.get(key), bool)
        }
        if flags and isinstance(current.get("sites"), list):
            current["sites"] = [
                {**item, "enabled": flags[item["name"]]} if item.get("name") in flags else item
                for item in current["sites"]
            ]
    sites = current.get("sites")
    if not isinstance(sites, list):
        legacy = {
            key: current[key]
            for key in ("javdb", "tmdb", "imdb")
            if isinstance(current.get(key), bool)
        }
        priority = current.get("priority") if isinstance(current.get("priority"), str) else None
        sites = normalize_sites(None, legacy or None, priority)
    else:
        sites = normalize_sites(sites)
    payload = {
        "media_dir": str(current.get("media_dir") or ""),
        "output_dir": str(current.get("output_dir") or ""),
        "output_mode": current.get("output_mode") if current.get("output_mode") in {"beside", "folder"} else "beside",
        "sites": sites,
        "tmdb_key": str(current.get("tmdb_key") or ""),
        "proxy": str(current.get("proxy") or ""),
        "skip_existing_nfo": bool(current.get("skip_existing_nfo", True)),
        "translate_plot": bool(current.get("translate_plot", True)),
    }
    CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_job(settings: dict, stop_check, log, progress) -> None:
    media = (settings.get("media_dir") or "").strip()
    mode = settings.get("output_mode") or "beside"
    output = (settings.get("output_dir") or "").strip()
    scrape(
        Path(media),
        mode=mode,
        output_dir=Path(output) if output else None,
        use_imdb=bool(settings.get("imdb", True)),
        sources=settings,
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
    parser.add_argument("--output", help="复制模式下的输出目录")
    parser.add_argument(
        "--mode",
        choices=["beside", "folder"],
        help="beside=只在视频旁边写 nfo 和封面；folder=按《标题 (年份)》建文件夹并复制",
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
    media = args.media if args.media is not None else config["media_dir"]
    output = args.output if args.output is not None else config["output_dir"]
    mode = args.mode or config["output_mode"]
    sites = normalize_sites(config.get("sites"))
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
        "media_dir": media,
        "output_dir": output,
        "output_mode": mode,
        "sites": sites,
        "tmdb_key": tmdb_key,
        "proxy": config.get("proxy") or "",
        "skip_existing_nfo": bool(config.get("skip_existing_nfo", True)),
        "translate_plot": bool(config.get("translate_plot", True)),
    }
    save_config(settings)
    print(
        f"模式: {'旁边写 nfo/封面' if mode == 'beside' else '建文件夹并复制'}；"
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
