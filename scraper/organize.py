"""Scan a media folder, write NFO and artwork, optionally copy into a new folder.

Beside mode leaves the video where it is. Folder mode renames and moves it.
Folder layout follows MDC: ``输出/演员/番号或标题/``.
Beside the nfo, in both modes: ``poster.jpg``, ``fanart.jpg``, ``thumb.jpg``.
``extrafanart/extrafanart-N.jpg`` only when the source actually has stills.
The nfo name is always ``{视频文件名}.nfo``.
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
from scraper.sources import CODE_SITES, SITE_LABELS, TITLE_SITES, enabled_names, normalize_sites
from scraper.tmdb import lookup as tmdb_lookup
from scraper.translate import has_cjk, translate_to_zh

SKIP_DIR_NAMES = {"failed", ".actors"}
_INVALID_FOLDER_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_LABELS = SITE_LABELS
_CODE_SITES = set(CODE_SITES)
_TITLE_SITES = set(TITLE_SITES)

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]
StopFn = Callable[[], bool]


def list_videos(root: Path) -> list[Path]:
    """Video files under ``root``, skipping hidden, ``failed``, and ``.actors`` dirs."""

    root = Path(root)
    found: list[Path] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name.lower() not in SKIP_DIR_NAMES
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            extension = os.path.splitext(filename)[1].lower().lstrip(".")
            if extension in VIDEO_EXTENSIONS:
                found.append(Path(dirpath) / filename)
    found.sort()
    return found


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
    if mode not in {"beside", "folder"}:
        log(f"未知输出方式: {mode}")
        return
    if not media_dir.is_dir():
        log(f"媒体目录不存在: {media_dir}")
        return
    if mode == "folder":
        if output_dir is None or not str(output_dir).strip():
            log("「按演员/标题改名并移动」需要选择输出目录")
            return
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    proxy_url, warning = classify_proxy(options["proxy"])
    if warning:
        log(warning)
    options["proxy"] = proxy_url

    files = list_videos(media_dir)
    total = len(files)
    order = enabled_names(options.get("sites"))
    log("数据源顺序: " + (", ".join(_LABELS[name] for name in order) if order else "（无）"))
    log(f"扫描完成，共 {total} 个视频")
    progress(0, total, "")
    if total == 0:
        return

    for index, src in enumerate(files, start=1):
        if stop_check():
            log("已停止")
            return
        progress(index, total, src.name)
        try:
            used_network = _process_one(
                src,
                mode=mode,
                output_dir=output_dir,
                options=options,
                log=log,
            )
        except Exception as exc:
            log(f"处理失败 {src.name}: {exc}")
            used_network = False
        if used_network and pause_seconds and index < total and not stop_check():
            time.sleep(pause_seconds)
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
    if mode not in {"beside", "folder"}:
        log(f"未知输出方式: {mode}")
        return
    if mode == "folder":
        if output_dir is None or not str(output_dir).strip():
            log("「按演员/标题改名并移动」需要选择输出目录")
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
            mode=mode,
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
    if sources is None:
        sites = normalize_sites([
            {"name": name, "enabled": name == "imdb" and bool(use_imdb)}
            for name in ("javdb", "javbus", "tmdb", "imdb", "dmm", "avsox", "mgstage", "fc2")
        ])
        return {
            "sites": sites,
            "tmdb_key": "",
            "proxy": "",
            "skip_existing_nfo": False,
            "translate_plot": False,
        }
    if isinstance(sources.get("sites"), list):
        sites = normalize_sites(sources.get("sites"))
    else:
        legacy = {}
        for key in ("javdb", "tmdb", "imdb"):
            if key in sources:
                legacy[key] = bool(sources.get(key))
        if "imdb" not in legacy:
            legacy["imdb"] = bool(use_imdb)
        sites = normalize_sites(None, legacy, sources.get("priority") if isinstance(sources.get("priority"), str) else None)
    return {
        "sites": sites,
        "tmdb_key": str(sources.get("tmdb_key") or ""),
        "proxy": str(sources.get("proxy") or ""),
        "skip_existing_nfo": bool(sources.get("skip_existing_nfo", True)),
        "translate_plot": bool(sources.get("translate_plot", True)),
    }


def _process_one(
    src: Path,
    *,
    mode: str,
    output_dir: Path | None,
    options: dict,
    log: LogFn,
) -> bool:
    parsed = parse_filename(src.name)
    log(
        f"{src.name} -> IMDb {parsed.imdb_id or '-'} / "
        f"番号 {parsed.code or '-'} / 标题 {parsed.title or '-'}"
    )
    if options["skip_existing_nfo"] and mode == "beside" and src.with_suffix(".nfo").exists():
        log(f"已有 NFO，跳过 {src.name}")
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

    if options["translate_plot"] and meta.plot and not has_cjk(meta.plot):
        try:
            meta.plot = translate_to_zh(meta.plot, proxy=options["proxy"])
            log("简介已翻译为简体中文")
            used_network = True
        except Exception as exc:
            log(f"简介翻译失败，保留原文: {exc}")

    if mode == "folder":
        if output_dir is None:
            log("缺少输出目录，跳过移动")
            return used_network
        folder = movie_folder(output_dir, meta)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / video_filename(src, meta)
        nfo_path = destination.with_suffix(".nfo")
        if options["skip_existing_nfo"] and nfo_path.exists():
            log(f"已有 NFO，跳过 {nfo_path}")
            return used_network
        if destination.resolve() == src.resolve():
            log(f"输出路径与原文件相同，不移动: {destination}")
        elif destination.exists():
            log(f"目标已存在，不覆盖、不移动原文件: {destination}")
        else:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.move(src, destination)
            log(f"已改名并移动: {src.name} -> {destination}")
        artwork_dir = folder
    else:
        nfo_path = src.with_suffix(".nfo")
        artwork_dir = src.parent

    artwork = _save_artwork(meta, artwork_dir, options["proxy"], log)
    actor_files = _save_actor_photos(meta, artwork_dir, options["proxy"], log)
    write_nfo(nfo_path, meta, artwork=artwork, actor_files=actor_files)
    log(f"写入 {nfo_path.name}")
    return used_network



def video_filename(src: Path, meta: MovieMetadata) -> str:
    """``番号-标题.ext``. Title already starting with the code is not repeated."""

    code = (meta.code or "").strip()
    title = (meta.title or "").strip()
    if code and title and not title.upper().startswith(code.upper()):
        stem = f"{code}-{title}"
    else:
        stem = title or code or src.stem
    stem = sanitize_folder_name(stem)
    if len(stem) > 80:
        stem = stem[:80].rstrip(" .-")
    return (stem or src.stem) + src.suffix


def movie_folder(output_dir: Path, meta: MovieMetadata) -> Path:
    """``输出/第一位演员/番号或标题``，没有演员时是 ``输出/番号或标题``。"""

    title = sanitize_folder_name(meta.code or meta.title or "未知")
    actor = ""
    if meta.cast:
        actor = sanitize_folder_name(meta.cast[0])
        if actor == "未知":
            actor = ""
    if actor:
        return Path(output_dir) / actor / title
    return Path(output_dir) / title


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
    filename = f"{cleaned[:80]}{ext}"
    if filename in used:
        return ""
    used.add(filename)
    return filename


def _save_artwork(meta: MovieMetadata, folder: Path, proxy: str | None, log: LogFn) -> dict[str, bool]:
    poster = folder / "poster.jpg"
    fanart = folder / "fanart.jpg"
    thumb = folder / "thumb.jpg"
    flags = {"poster": False, "fanart": False, "thumb": False}
    if meta.poster_url:
        flags["poster"] = _save_image(meta.poster_url, poster, proxy, log)
    if meta.fanart_url and meta.fanart_url != meta.poster_url:
        flags["fanart"] = _save_image(meta.fanart_url, fanart, proxy, log)
    elif flags["poster"] or poster.exists():
        flags["fanart"] = _copy_image(poster, fanart, log)
    if meta.thumb_url and meta.thumb_url not in {meta.poster_url, meta.fanart_url}:
        flags["thumb"] = _save_image(meta.thumb_url, thumb, proxy, log)
    elif flags["poster"] or poster.exists():
        flags["thumb"] = _copy_image(poster, thumb, log)
    stills = [url for url in (meta.extra_stills or []) if url][:20]
    if stills:
        extra = folder / "extrafanart"
        extra.mkdir(exist_ok=True)
        saved = 0
        for index, url in enumerate(stills, start=1):
            path = extra / f"extrafanart-{index}.jpg"
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
