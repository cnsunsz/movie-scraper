"""Scan a media folder, write NFO and artwork, optionally move / rename / symlink.

Main modes (MDC-aligned):
  1       organize + NFO + images, rename and move
  1_keep  organize + NFO + images, move keeping original filename
  2       move by location rule (scrape when possible; still move on miss)
  4       scrape in place (NFO + images beside file, no move)
  5       scrape in place and rename using naming_rule

``link_mode``: move (default) or soft_link (symlink into output). Hard link / strm
are not supported. Beside the nfo: ``poster.jpg``, ``fanart.jpg``, ``thumb.jpg``.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Callable

from scraper.avsox import lookup_code as avsox_lookup
from scraper.dmm import lookup_code as dmm_lookup
from scraper.fc2 import fc2_id, lookup_code as fc2_lookup
from scraper.imdb import MovieMetadata, download_file, fetch_by_id, search_title
from scraper.javbus import lookup_code as javbus_lookup
from scraper.javdb import lookup_code
from scraper.match import CodeMismatch
from scraper.mgstage import lookup_code as mgstage_lookup
from scraper.net import classify_proxy
from scraper.nfo import write_nfo
from scraper.parser import VIDEO_EXTENSIONS, parse_filename
from scraper.naming import apply_delete_chars, eval_rule, rule_values, truncate_title
from scraper.sources import CODE_SITES, SITE_LABELS, TITLE_SITES, enabled_names, normalize_sites
from scraper.tmdb import lookup as tmdb_lookup
from scraper.translate import has_cjk, translate_to_zh

SKIP_DIR_NAMES = {"failed", ".actors"}
MAIN_MODES = ("1", "1_keep", "2", "4", "5")
LINK_MODES = ("move", "soft_link")
_INVALID_FOLDER_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_LABELS = SITE_LABELS
_CODE_SITES = set(CODE_SITES)
_TITLE_SITES = set(TITLE_SITES)

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]
StopFn = Callable[[], bool]


def list_videos(
    root: Path,
    *,
    excluded_folders: str | None = None,
    excluded_size_mb: float = 0,
) -> list[Path]:
    """Video files under ``root``, skipping hidden / failed / .actors and config exclusions."""

    root = Path(root)
    found: list[Path] = []
    if not root.is_dir():
        return found
    skip = {name.lower() for name in SKIP_DIR_NAMES}
    if excluded_folders:
        for token in str(excluded_folders).split(","):
            name = token.strip().lower()
            if name:
                skip.add(name)
    min_bytes = int(float(excluded_size_mb or 0) * 1024 * 1024)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name.lower() not in skip
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            extension = os.path.splitext(filename)[1].lower().lstrip(".")
            if extension not in VIDEO_EXTENSIONS:
                continue
            path = Path(dirpath) / filename
            if min_bytes > 0:
                try:
                    if path.stat().st_size < min_bytes:
                        continue
                except OSError:
                    continue
            found.append(path)
    found.sort()
    return found



def _resolve_main_mode(mode: str, sources: dict | None) -> str:
    """Accept main_mode (1/1_keep/2/4/5) or legacy beside/folder."""

    if isinstance(sources, dict):
        raw = sources.get("main_mode")
        if isinstance(raw, int):
            raw = str(raw)
        if raw in MAIN_MODES:
            return raw
    if mode in MAIN_MODES:
        return mode
    if mode == "folder":
        return "1"
    if mode == "beside":
        return "4"
    return "4"


def _needs_output(main_mode: str) -> bool:
    return main_mode in {"1", "1_keep", "2"}


def scrape(
    media_dir: Path,
    *,
    mode: str,
    output_dir: Path | None,
    use_imdb: bool = True,
    sources: dict | None = None,
    stop_check: StopFn,
    log: LogFn,
    progress: ProgressFn,
    pause_seconds: float = 0.3,
) -> None:
    """Process every video. ``stop_check`` is consulted between files.

    ``sources`` carries the window/CLI options. When it is omitted, only the
    ``use_imdb`` flag is honored so older callers do not touch JavDB or TMDB.
    """

    media_dir = Path(media_dir)
    options = _options(use_imdb, sources)
    main_mode = _resolve_main_mode(mode, sources)
    options["main_mode"] = main_mode
    if main_mode not in MAIN_MODES:
        log(f"未知主运行模式: {main_mode}")
        return
    if not media_dir.is_dir():
        log(f"媒体目录不存在: {media_dir}")
        return
    if _needs_output(main_mode):
        if output_dir is None or not str(output_dir).strip():
            log("当前主运行模式需要选择输出目录")
            return
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    proxy_url, warning = classify_proxy(options["proxy"])
    if warning:
        log(warning)
    options["proxy"] = proxy_url

    film_label = "一般影片" if options.get("film_type") == "general" else "其他影片"
    mode_labels = {
        "1": "整理+NFO+图片+改名移动",
        "1_keep": "整理+NFO+图片+保留原名移动",
        "2": "仅位置规则整理/移动",
        "4": "原地刮削",
        "5": "原地刮削并重命名",
    }
    log(f"影片类型: {film_label}")
    log(f"主运行模式: {main_mode}（{mode_labels.get(main_mode, main_mode)}）")
    link_mode = options.get("link_mode") or "move"
    if link_mode == "soft_link":
        log("整理方式: 软链接（symlink）")
    else:
        log("整理方式: 移动")
    files = list_videos(
        media_dir,
        excluded_folders=options.get("excluded_folders"),
        excluded_size_mb=float(options.get("excluded_size_mb") or 0),
    )
    total = len(files)
    order = enabled_names(options.get("sites"))
    log("数据源顺序: " + (", ".join(_LABELS[name] for name in order) if order else "（无）"))
    log(f"扫描完成，共 {total} 个视频")
    progress(0, total, "")
    if total == 0:
        return

    pause = float(options.get("sleep_seconds") or pause_seconds or 0)
    for index, src in enumerate(files, start=1):
        if stop_check():
            log("已停止")
            return
        progress(index, total, src.name)
        try:
            used_network = _process_one(
                src,
                output_dir=output_dir,
                options=options,
                log=log,
            )
        except Exception as exc:
            log(f"处理失败 {src.name}: {exc}")
            used_network = False
        if used_network and pause and index < total and not stop_check():
            time.sleep(pause)
    if stop_check():
        log("已停止")
        return
    log("全部完成")


def scrape_one(
    video: Path,
    *,
    mode: str,
    output_dir: Path | None,
    sources: dict | None = None,
    stop_check: StopFn,
    log: LogFn,
    progress: ProgressFn | None = None,
) -> None:
    """Scrape a single video file with the same rules as ``scrape``."""

    video = Path(video)
    if not video.is_file():
        log(f"文件不存在: {video}")
        return
    options = _options(True, sources)
    main_mode = _resolve_main_mode(mode, sources)
    options["main_mode"] = main_mode
    if main_mode not in MAIN_MODES:
        log(f"未知主运行模式: {main_mode}")
        return
    if _needs_output(main_mode):
        if output_dir is None or not str(output_dir).strip():
            log("当前主运行模式需要选择输出目录")
            return
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    proxy_url, warning = classify_proxy(options["proxy"])
    if warning:
        log(warning)
    options["proxy"] = proxy_url
    order = enabled_names(options.get("sites"))
    log("数据源顺序: " + (", ".join(_LABELS[name] for name in order) if order else "（无）"))
    if progress:
        progress(1, 1, video.name)
    if stop_check():
        log("已停止")
        return
    try:
        _process_one(
            video,
            output_dir=output_dir,
            options=options,
            log=log,
        )
    except Exception as exc:
        log(f"处理失败 {video.name}: {exc}")
    if stop_check():
        log("已停止")
        return
    log("全部完成")


def _options(use_imdb: bool, sources: dict | None) -> dict:
    film_type = "other"
    if isinstance(sources, dict) and sources.get("film_type") in {"general", "other"}:
        film_type = sources["film_type"]
    if sources is None:
        sites = normalize_sites([
            {"name": name, "enabled": name == "imdb" and bool(use_imdb)}
            for name in ("javdb", "javbus", "tmdb", "imdb", "dmm", "avsox", "mgstage", "fc2")
        ], film_type=film_type)
        return {
            "film_type": film_type,
            "sites": sites,
            "tmdb_key": "",
            "proxy": "",
            "main_mode": "4",
            "link_mode": "move",
            "skip_existing_nfo": False,
            "translate_plot": False,
            "download_images": True,
            "download_missing_only": False,
            "print_nfo": True,
            "nfo_skip_days": 0,
            "excluded_folders": "failed,.actors",
            "excluded_size_mb": 0,
            "location_rule": "actor+'/'+number" if film_type == "other" else "genres+'/'+title",
            "naming_rule": "number+'-'+title" if film_type == "other" else "title.year",
            "max_title_len": 80,
            "delete_chars": "",
            "number_exclude_chars": "",
            "uppercase_name": False,
            "anonymous_fill": film_type == "other",
            "actor_only_tag": False,
            "extrafanart": True,
            "trailer": False,
            "storyline": False,
            "tpdb_token": "",
            "sleep_seconds": 0.3,
        }
    if isinstance(sources.get("sites"), list):
        sites = normalize_sites(sources.get("sites"), film_type=film_type)
    else:
        legacy = {}
        for key in ("javdb", "tmdb", "imdb"):
            if key in sources:
                legacy[key] = bool(sources.get(key))
        if "imdb" not in legacy:
            legacy["imdb"] = bool(use_imdb)
        sites = normalize_sites(
            None,
            legacy,
            sources.get("priority") if isinstance(sources.get("priority"), str) else None,
            film_type=film_type,
        )
    default_location = "genres+'/'+title" if film_type == "general" else "actor+'/'+number"
    default_naming = "title.year" if film_type == "general" else "number+'-'+title"
    main_mode = sources.get("main_mode")
    if isinstance(main_mode, int):
        main_mode = str(main_mode)
    if main_mode not in MAIN_MODES:
        legacy_mode = sources.get("output_mode")
        if legacy_mode == "folder":
            main_mode = "1"
        else:
            main_mode = "4"
    link_mode = sources.get("link_mode") if sources.get("link_mode") in LINK_MODES else "move"
    return {
        "film_type": film_type,
        "sites": sites,
        "tmdb_key": str(sources.get("tmdb_key") or ""),
        "proxy": str(sources.get("proxy") or ""),
        "main_mode": main_mode,
        "link_mode": link_mode,
        "skip_existing_nfo": bool(sources.get("skip_existing_nfo", True)),
        "translate_plot": bool(sources.get("translate_plot", film_type != "general")),
        "download_images": bool(sources.get("download_images", True)),
        "download_missing_only": bool(sources.get("download_missing_only", False)),
        "print_nfo": bool(sources.get("print_nfo", True)),
        "nfo_skip_days": int(sources.get("nfo_skip_days") or 0),
        "excluded_folders": str(sources.get("excluded_folders") or "failed,.actors"),
        "excluded_size_mb": float(sources.get("excluded_size_mb") or 0),
        "location_rule": str(sources.get("location_rule") or default_location),
        "naming_rule": str(sources.get("naming_rule") or default_naming),
        "max_title_len": int(sources.get("max_title_len") or 80),
        "delete_chars": str(sources.get("delete_chars") or ""),
        "number_exclude_chars": str(sources.get("number_exclude_chars") or ""),
        "uppercase_name": bool(sources.get("uppercase_name", False)),
        "anonymous_fill": bool(sources.get("anonymous_fill", film_type == "other")),
        "actor_only_tag": bool(sources.get("actor_only_tag", False)),
        "extrafanart": bool(sources.get("extrafanart", True)),
        "trailer": bool(sources.get("trailer", False)),
        "storyline": bool(sources.get("storyline", False)),
        "tpdb_token": str(sources.get("tpdb_token") or ""),
        "sleep_seconds": float(sources.get("sleep_seconds") or 0.3),
    }


def _nfo_fresh(path: Path, skip_days: int) -> bool:
    if skip_days <= 0 or not path.exists():
        return False
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < skip_days * 86400


def _place_video(src: Path, destination: Path, link_mode: str, log: LogFn) -> bool:
    """Move or soft-link ``src`` to ``destination``. Returns False if skipped."""

    if destination.resolve() == src.resolve():
        log(f"输出路径与原文件相同，不移动: {destination}")
        return True
    if destination.exists():
        log(f"目标已存在，不覆盖、不移动原文件，跳过写入: {destination}")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if link_mode == "soft_link":
        try:
            os.symlink(src, destination)
            log(f"已创建软链接: {src.name} -> {destination}")
            return True
        except OSError as exc:
            log(f"软链接失败（Windows 可能需要开发者模式或管理员权限）: {exc}")
            log("回退为移动文件")
    shutil.move(str(src), str(destination))
    log(f"已改名并移动: {src.name} -> {destination}")
    return True


def _process_one(
    src: Path,
    *,
    output_dir: Path | None,
    options: dict,
    log: LogFn,
) -> bool:
    exclude = str(options.get("number_exclude_chars") or "")
    parsed = parse_filename(src.name, exclude_chars=exclude)
    log(
        f"{src.name} -> IMDb {parsed.imdb_id or '-'} / "
        f"番号 {parsed.code or '-'} / 标题 {parsed.title or '-'}"
    )
    if options.get("tpdb_token"):
        log("TPDB Token 已配置（刮削器暂未接入，已忽略）")
    if options.get("trailer"):
        log("预告片开关已开：暂未实现")
    if options.get("storyline"):
        log("剧情简介扩展开关已开：暂未实现")

    main_mode = options.get("main_mode") or "4"
    link_mode = options.get("link_mode") if options.get("link_mode") in LINK_MODES else "move"
    write_meta = main_mode != "2"  # mode 2 is move-first; meta optional
    do_rename = main_mode in {"1", "5"}
    do_move = main_mode in {"1", "1_keep", "2"}
    keep_name = main_mode in {"1_keep", "2", "4"}

    # Skip checks for in-place nfo
    if main_mode in {"4", "5"}:
        nfo_probe = src.with_suffix(".nfo")
        if options["skip_existing_nfo"] and nfo_probe.exists() and main_mode == "4":
            log(f"已有 NFO，跳过 {src.name}")
            return False
        if main_mode == "4" and _nfo_fresh(nfo_probe, int(options.get("nfo_skip_days") or 0)):
            log(f"NFO 未过期（nfo_skip_days），跳过 {src.name}")
            return False

    meta, used_network = _lookup(parsed, options, log)
    if meta is None or not meta.title:
        fallback = parsed.title or parsed.code or src.stem
        meta = MovieMetadata(
            title=fallback,
            original_title=fallback,
            year=parsed.year or "",
            code=parsed.code or "",
        )
    else:
        if not meta.code:
            meta.code = parsed.code or ""
        if not meta.year and parsed.year:
            meta.year = parsed.year
        log(f"使用 {_LABELS.get(meta.source, meta.source or '文件名')}: {meta.title}")

    if options.get("anonymous_fill") and not any((name or "").strip() for name in (meta.cast or [])):
        meta.cast = ["佚名"]
        log("匿名演员填充: 佚名")

    if options["translate_plot"] and meta.plot and not has_cjk(meta.plot):
        try:
            meta.plot = translate_to_zh(meta.plot, proxy=options["proxy"])
            log("简介已翻译为简体中文")
            used_network = True
        except Exception as exc:
            log(f"简介翻译失败，保留原文: {exc}")

    # Mode 2: still prefer scrape, but always try to move even with filename-only meta
    if do_move:
        if output_dir is None:
            log("缺少输出目录，跳过移动")
            return used_network
        folder = movie_folder(
            output_dir,
            meta,
            location_rule=options.get("location_rule") or "",
            delete_chars=options.get("delete_chars") or "",
            uppercase_name=bool(options.get("uppercase_name")),
            max_title_len=int(options.get("max_title_len") or 80),
        )
        folder.mkdir(parents=True, exist_ok=True)
        if keep_name or not do_rename:
            destination = folder / src.name
        else:
            destination = folder / video_filename(
                src,
                meta,
                naming_rule=options.get("naming_rule") or "",
                delete_chars=options.get("delete_chars") or "",
                uppercase_name=bool(options.get("uppercase_name")),
                max_title_len=int(options.get("max_title_len") or 80),
            )
        nfo_path = destination.with_suffix(".nfo")
        if write_meta and options["skip_existing_nfo"] and nfo_path.exists():
            log(f"已有 NFO，跳过 {nfo_path}")
            return used_network
        if write_meta and _nfo_fresh(nfo_path, int(options.get("nfo_skip_days") or 0)):
            log(f"NFO 未过期（nfo_skip_days），跳过 {nfo_path}")
            return used_network
        placed = _place_video(src, destination, link_mode, log)
        if not placed:
            return used_network
        # After move, src may be gone; work against destination
        work = destination if destination.exists() else src
        artwork_dir = folder
        nfo_path = work.with_suffix(".nfo")
    elif main_mode == "5":
        # Rename in place
        new_name = video_filename(
            src,
            meta,
            naming_rule=options.get("naming_rule") or "",
            delete_chars=options.get("delete_chars") or "",
            uppercase_name=bool(options.get("uppercase_name")),
            max_title_len=int(options.get("max_title_len") or 80),
        )
        destination = src.with_name(new_name)
        if destination.resolve() != src.resolve():
            if destination.exists():
                log(f"目标已存在，不覆盖、不重命名: {destination}")
                return used_network
            src.rename(destination)
            log(f"已原地重命名: {src.name} -> {destination.name}")
            src = destination
        nfo_path = src.with_suffix(".nfo")
        artwork_dir = src.parent
        if options["skip_existing_nfo"] and nfo_path.exists():
            # Still renamed; skip rewriting nfo if requested
            log(f"已有 NFO，跳过写入 {nfo_path.name}")
            return used_network
        if _nfo_fresh(nfo_path, int(options.get("nfo_skip_days") or 0)):
            log(f"NFO 未过期（nfo_skip_days），跳过 {nfo_path.name}")
            return used_network
    else:
        # mode 4 beside
        nfo_path = src.with_suffix(".nfo")
        artwork_dir = src.parent

    if not write_meta:
        # Mode 2: optional minimal meta — write nfo only when we actually scraped
        if meta.source and options.get("print_nfo", True):
            write_meta = True
        else:
            log("模式2：无刮削数据，仅完成移动/链接")
            return used_network

    if options.get("download_images", True):
        artwork = _save_artwork(
            meta,
            artwork_dir,
            options["proxy"],
            log,
            missing_only=bool(options.get("download_missing_only")),
            extrafanart=bool(options.get("extrafanart", True)),
        )
        actor_files = _save_actor_photos(meta, artwork_dir, options["proxy"], log)
    else:
        log("已关闭下载图片")
        artwork = {
            "poster": (artwork_dir / "poster.jpg").exists(),
            "fanart": (artwork_dir / "fanart.jpg").exists(),
            "thumb": (artwork_dir / "thumb.jpg").exists(),
        }
        actor_files = {}
    if options.get("print_nfo", True):
        write_nfo(
            nfo_path,
            meta,
            artwork=artwork,
            actor_files=actor_files,
            actor_only_tag=bool(options.get("actor_only_tag")),
        )
        log(f"写入 {nfo_path.name}")
    else:
        log("已关闭写入 NFO")
    return used_network


def video_filename(
    src: Path,
    meta: MovieMetadata,
    *,
    naming_rule: str = "",
    delete_chars: str = "",
    uppercase_name: bool = False,
    max_title_len: int = 80,
) -> str:
    """Build video stem from ``naming_rule`` (default ``number-title``)."""

    values = rule_values(meta, suffix=src.suffix.lstrip("."))
    if uppercase_name and values.get("number"):
        values["number"] = values["number"].upper()
        if values.get("prefix"):
            values["prefix"] = values["prefix"].upper()
    rule = (naming_rule or "").strip() or "number+'-'+title"
    code = (values.get("number") or "").strip()
    title = (values.get("title") or "").strip()
    # When the title already starts with the code, avoid number+title doubling
    rule_compact = rule.replace(" ", "").lower()
    if (
        code
        and title
        and title.upper().startswith(code.upper())
        and "number" in rule_compact
        and "title" in rule_compact
    ):
        stem = eval_rule("title", values, default="") or title
    else:
        stem = eval_rule(rule, values, default="")
    if not stem:
        if code and title and not title.upper().startswith(code.upper()):
            stem = f"{code}-{title}"
        else:
            stem = title or code or src.stem
    stem = apply_delete_chars(stem, delete_chars)
    stem = sanitize_folder_name(stem)
    stem = truncate_title(stem, max_title_len if max_title_len > 0 else 80)
    return (stem or src.stem) + src.suffix


def movie_folder(
    output_dir: Path,
    meta: MovieMetadata,
    *,
    location_rule: str = "",
    delete_chars: str = "",
    uppercase_name: bool = False,
    max_title_len: int = 80,
) -> Path:
    """Folder under ``output_dir`` from ``location_rule`` (default actor/number)."""

    values = rule_values(meta)
    if uppercase_name and values.get("number"):
        values["number"] = values["number"].upper()
        if values.get("prefix"):
            values["prefix"] = values["prefix"].upper()
    rule = (location_rule or "").strip() or "actor+'/'+number"
    relative = eval_rule(rule, values, default="")
    if not relative:
        # Legacy fallback: actor/number-or-title
        title = sanitize_folder_name(meta.code or meta.title or "未知")
        actor = ""
        if meta.cast:
            actor = sanitize_folder_name(meta.cast[0])
            if actor == "未知":
                actor = ""
        relative = f"{actor}/{title}" if actor else title
    relative = apply_delete_chars(relative, delete_chars)
    parts = []
    for part in relative.replace("\\", "/").split("/"):
        cleaned = sanitize_folder_name(part)
        cleaned = truncate_title(cleaned, max_title_len if max_title_len > 0 else 120)
        if cleaned and cleaned != "未知":
            parts.append(cleaned)
        elif cleaned == "未知" and not parts:
            parts.append(cleaned)
    if not parts:
        parts = [sanitize_folder_name(meta.code or meta.title or "未知")]
    return Path(output_dir).joinpath(*parts)



def _lookup(parsed, options: dict, log: LogFn) -> tuple[MovieMetadata | None, bool]:
    order = enabled_names(options.get("sites"))
    proxy = options["proxy"] or None
    used_network = False
    if not order:
        log("没有启用的数据源，仅使用文件名")
        return None, False
    code_sites = [name for name in order if name in _CODE_SITES]
    title_sites = [name for name in order if name in _TITLE_SITES]
    if code_sites and not parsed.code:
        log("没有番号，跳过番号网站")
    if title_sites and not parsed.title and not parsed.imdb_id:
        log("没有标题，跳过标题网站")
    skipped_fc2 = False
    for name in order:
        label = _LABELS.get(name, name)
        if name in _CODE_SITES and not parsed.code:
            continue
        if name == "fc2" and parsed.code and not fc2_id(parsed.code):
            if not skipped_fc2:
                log("没有 FC2 番号，跳过 FC2")
                skipped_fc2 = True
            continue
        if name in _TITLE_SITES and not parsed.title and not parsed.imdb_id:
            continue
        if name == "tmdb" and not (options.get("tmdb_key") or "").strip():
            log("TMDB 已勾选但没有 API Key，已跳过")
            continue
        try:
            meta, called = _query_one(name, parsed, options, proxy, log)
        except CodeMismatch as exc:
            log(f"{label} {exc}，已跳过")
            used_network = True
            continue
        except Exception as exc:
            log(f"{label} 失败: {exc}")
            used_network = True
            continue
        used_network = used_network or called
        if meta is not None and meta.title:
            return meta, used_network
        if called:
            log(f"{label} 没有结果")
    return None, used_network


def _query_one(name, parsed, options, proxy, log: LogFn) -> tuple[MovieMetadata | None, bool]:
    label = _LABELS.get(name, name)
    if name == "javdb":
        log(f"查询 JavDB {parsed.code}")
        return lookup_code(parsed.code, proxy=proxy), True
    if name == "javbus":
        log(f"查询 JavBus {parsed.code}")
        return javbus_lookup(parsed.code, proxy=proxy), True
    if name == "dmm":
        log(f"查询 DMM {parsed.code}")
        return dmm_lookup(parsed.code, proxy=proxy), True
    if name == "avsox":
        log(f"查询 AVSOX {parsed.code}")
        return avsox_lookup(parsed.code, proxy=proxy), True
    if name == "mgstage":
        log(f"查询 MGStage {parsed.code}")
        return mgstage_lookup(parsed.code, proxy=proxy), True
    if name == "fc2":
        log(f"查询 FC2 {parsed.code}")
        return fc2_lookup(parsed.code, proxy=proxy), True
    if name == "tmdb":
        if parsed.imdb_id:
            log(f"查询 TMDB {parsed.imdb_id}")
        else:
            log(f"查询 TMDB {parsed.title}")
        movie = tmdb_lookup(
            api_key=options["tmdb_key"],
            imdb_id=parsed.imdb_id,
            title=parsed.title,
            year=parsed.year,
            proxy=proxy,
        )
        return movie, True
    if name == "imdb":
        if parsed.imdb_id:
            log(f"查询 IMDb {parsed.imdb_id}")
            return fetch_by_id(parsed.imdb_id, proxy=proxy), True
        log(f"查询 IMDb {parsed.title}")
        return search_title(parsed.title, year=parsed.year, proxy=proxy), True
    log(f"{label} 跳过：未知网站")
    return None, False



def _save_actor_photos(meta: MovieMetadata, folder: Path, proxy: str | None, log: LogFn) -> dict[str, str]:
    """Download actor portraits into ``.actors`` next to the nfo. Names stay in the nfo either way."""

    names = [name.strip() for name in (meta.cast or []) if (name or "").strip()]
    if not names:
        return {}
    photos = meta.actor_photos or {}
    saved: dict[str, str] = {}
    used: set[str] = set()
    dest_root = folder / ".actors"
    downloaded = 0
    for name in names:
        url = photos.get(name) or ""
        if not url:
            continue
        filename = _actor_filename(name, url, used)
        if not filename:
            log(f"演员文件名无效，仍写入 NFO: {name}")
            continue
        dest_root.mkdir(parents=True, exist_ok=True)
        path = dest_root / filename
        if _save_image(url, path, proxy, log):
            saved[name] = f".actors/{filename}"
            downloaded += 1
    if dest_root.exists() and not any(dest_root.iterdir()):
        dest_root.rmdir()
    missing = len(names) - len(saved)
    log(f"演员 {len(names)} 人写入 NFO，下载头像 {downloaded} 张" + (f"，{missing} 人没有头像地址" if missing else ""))
    return saved


def _actor_filename(name: str, url: str, used: set[str]) -> str:
    cleaned = _INVALID_FOLDER_CHARS.sub(" ", name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        return ""
    ext = ".jpg"
    path = url.split("?", 1)[0].lower()
    for candidate in (".jpeg", ".jpg", ".png", ".webp"):
        if path.endswith(candidate):
            ext = ".jpg" if candidate == ".jpeg" else candidate
            break
    base = cleaned[:80]
    filename = f"{base}{ext}"
    index = 2
    while filename in used:
        suffix = f" ({index})"
        keep = max(1, 80 - len(suffix))
        filename = f"{base[:keep]}{suffix}{ext}"
        index += 1
        if index > 99:
            return ""
    used.add(filename)
    return filename


def _save_artwork(
    meta: MovieMetadata,
    folder: Path,
    proxy: str | None,
    log: LogFn,
    *,
    missing_only: bool = False,
    extrafanart: bool = True,
) -> dict[str, bool]:
    poster = folder / "poster.jpg"
    fanart = folder / "fanart.jpg"
    thumb = folder / "thumb.jpg"
    flags = {"poster": False, "fanart": False, "thumb": False}

    def need(path: Path) -> bool:
        return not (missing_only and path.exists())

    if meta.poster_url and need(poster):
        flags["poster"] = _save_image(meta.poster_url, poster, proxy, log)
    elif poster.exists():
        flags["poster"] = True
    if meta.fanart_url and meta.fanart_url != meta.poster_url and need(fanart):
        flags["fanart"] = _save_image(meta.fanart_url, fanart, proxy, log)
    elif flags["poster"] or poster.exists():
        if need(fanart):
            flags["fanart"] = _copy_image(poster, fanart, log)
        else:
            flags["fanart"] = fanart.exists()
    if meta.thumb_url and meta.thumb_url not in {meta.poster_url, meta.fanart_url} and need(thumb):
        flags["thumb"] = _save_image(meta.thumb_url, thumb, proxy, log)
    elif flags["poster"] or poster.exists():
        if need(thumb):
            flags["thumb"] = _copy_image(poster, thumb, log)
        else:
            flags["thumb"] = thumb.exists()
    if extrafanart:
        stills = [url for url in (meta.extra_stills or []) if url][:20]
        if stills:
            extra = folder / "extrafanart"
            extra.mkdir(exist_ok=True)
            saved = 0
            for index, url in enumerate(stills, start=1):
                path = extra / f"extrafanart-{index}.jpg"
                if missing_only and path.exists():
                    saved += 1
                    continue
                if _save_image(url, path, proxy, log):
                    saved += 1
            if saved == 0 and not any(extra.iterdir()):
                extra.rmdir()
                log("没有下载到剧照，不保留空的 extrafanart")
    return flags


def _copy_image(src: Path, dest: Path, log: LogFn) -> bool:
    if dest.exists():
        log(f"已存在，跳过 {dest.name}")
        return True
    if not src.exists():
        return False
    shutil.copyfile(src, dest)
    log(f"复制 {src.name} 为 {dest.name}")
    return True


def _save_image(url: str, path: Path, proxy: str | None, log: LogFn) -> bool:
    if not url:
        return False
    try:
        result = download_file(url, path, proxy=proxy)
    except Exception as exc:
        log(f"下载失败 {path.name}: {exc}")
        return path.exists()
    if result == "skipped":
        log(f"已存在，跳过 {path.name}")
    else:
        log(f"下载 {path.name}")
    return True


def sanitize_folder_name(title: str, year: str = "") -> str:
    """Folder-safe name. Year is appended only when ``year`` is passed and the title has none."""

    title = _INVALID_FOLDER_CHARS.sub(" ", title or "").strip()
    title = re.sub(r"\s+", " ", title).strip(" .")
    year = (year or "").strip()
    if title and year and year not in title:
        name = f"{title} ({year})"
    else:
        name = title or year or "未知"
    name = name[:120].strip(" .")
    return name or "未知"
