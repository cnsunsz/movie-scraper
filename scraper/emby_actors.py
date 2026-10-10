"""Emby / Jellyfin actor avatar helpers.

Original implementation. URL shapes follow common Emby/Jellyfin REST
conventions (Persons list, Items/.../Images/Primary upload) and the public
Gfriends Filetree layout on GitHub. Not copied from MDCx.
"""

from __future__ import annotations

import base64
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from scraper.net import classify_proxy

LogFn = Callable[[str], None]
StopFn = Callable[[], bool]

GFRIENDS_RAW = "https://raw.githubusercontent.com/gfriends/gfriends/master"
GFRIENDS_FILETREE = f"{GFRIENDS_RAW}/Filetree.json"


def _opener(proxy: str | None):
    proxy_url, _warning = classify_proxy(proxy)
    handlers: list = []
    if proxy_url:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    return urllib.request.build_opener(*handlers)


def _normalize_server_base(server_type: str, base: str) -> str:
    """Strip a trailing ``/emby`` or ``/jellyfin`` so path joining does not double it."""

    root = (base or "").strip().rstrip("/")
    lowered = root.lower()
    if server_type == "jellyfin":
        for suffix in ("/jellyfin", "/emby"):
            if lowered.endswith(suffix):
                return root[: -len(suffix)].rstrip("/") or root
    else:
        if lowered.endswith("/emby"):
            return root[:-5].rstrip("/") or root
    return root


def _persons_url(server_type: str, base: str, api_key: str, user_id: str = "", limit: int | None = None) -> str:
    root = _normalize_server_base(server_type, base)
    if server_type == "jellyfin":
        path = f"{root}/Persons"
    else:
        path = f"{root}/emby/Persons"
    query = {"api_key": api_key}
    if user_id.strip():
        query["userid"] = user_id.strip()
    if limit is not None:
        query["Limit"] = str(limit)
    return f"{path}?{urllib.parse.urlencode(query)}"


def _primary_image_url(server_type: str, base: str, actor_id: str, api_key: str) -> str:
    root = _normalize_server_base(server_type, base)
    if server_type == "jellyfin":
        return f"{root}/Items/{actor_id}/Images/Primary?api_key={urllib.parse.quote(api_key)}"
    return f"{root}/emby/Items/{actor_id}/Images/Primary?api_key={urllib.parse.quote(api_key)}"


def test_connection(
    server_type: str,
    url: str,
    api_key: str,
    user_id: str = "",
    proxy: str | None = None,
) -> tuple[bool, str]:
    """Probe the Persons endpoint. Return ``(ok, message)``."""

    server_type = "jellyfin" if server_type == "jellyfin" else "emby"
    label = "Jellyfin" if server_type == "jellyfin" else "Emby"
    base = (url or "").strip()
    key = (api_key or "").strip()
    if not base:
        return False, f"{label} 服务器地址未填写"
    if not key:
        return False, f"{label} API 密钥未填写"
    endpoint = _persons_url(server_type, base, key, user_id, limit=1)
    opener = _opener(proxy)
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=20) as response:
            body = response.read(2_000_000)
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        return False, f"{label} 连接失败：HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{label} 连接失败：{exc}"
    if status >= 400:
        return False, f"{label} 连接失败：HTTP {status}"
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return False, f"{label} 返回了无法解析的内容"
    total = data.get("TotalRecordCount")
    items = data.get("Items") if isinstance(data.get("Items"), list) else []
    if total is None:
        total = len(items)
    return True, f"{label} 连接成功，演员约 {total} 人"


def _list_persons(
    server_type: str,
    url: str,
    api_key: str,
    user_id: str,
    proxy: str | None,
    log: LogFn,
) -> list[dict]:
    endpoint = _persons_url(server_type, url, api_key, user_id, limit=None)
    opener = _opener(proxy)
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=60) as response:
            body = response.read(20_000_000)
    except Exception as exc:
        log(f"获取演员列表失败: {exc}")
        return []
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        log("演员列表 JSON 解析失败")
        return []
    items = data.get("Items") if isinstance(data.get("Items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _load_gfriends_map(proxy: str | None, log: LogFn, cache_dir: Path | None = None) -> dict[str, str]:
    """Map ``姓名.jpg`` / ``姓名.png`` -> raw Content URL."""

    cache_path = (cache_dir or Path(tempfile.gettempdir())) / "movie-scraper-gfriends-filetree.json"
    opener = _opener(proxy)
    request = urllib.request.Request(GFRIENDS_FILETREE, headers={"User-Agent": "MovieScraper/1.0"})
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read(50_000_000)
        cache_path.write_bytes(raw)
        log("已下载 Gfriends Filetree.json")
    except Exception as exc:
        log(f"下载 Gfriends Filetree 失败: {exc}")
        if cache_path.is_file():
            log("改用本地缓存的 Filetree.json")
            raw = cache_path.read_bytes()
        else:
            return {}
    try:
        tree = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        log("Gfriends Filetree JSON 解析失败")
        return {}
    content = tree.get("Content")
    if not isinstance(content, dict):
        log("Gfriends Filetree 缺少 Content")
        return {}
    mapping: dict[str, str] = {}
    for folder, files in content.items():
        if not isinstance(files, dict):
            continue
        for name, filename in files.items():
            if not isinstance(filename, str):
                continue
            key = name if name.lower().endswith((".jpg", ".png", ".jpeg", ".webp")) else f"{name}.jpg"
            if key in mapping:
                continue
            mapping[key] = f"{GFRIENDS_RAW}/Content/{folder}/{filename}"
    log(f"Gfriends 索引共 {len(mapping)} 条")
    return mapping


def _load_local_map(folder: str, log: LogFn) -> dict[str, str]:
    root = Path(folder or "")
    if not root.is_dir():
        log("本地头像库目录不存在")
        return {}
    mapping: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        mapping[path.name] = str(path)
    if not mapping:
        log("本地头像库未发现图片")
    else:
        log(f"本地头像库共 {len(mapping)} 张")
    return mapping


def _lookup_avatar(name: str, mapping: dict[str, str]) -> str | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        key = f"{name}{ext}"
        if key in mapping:
            return mapping[key]
        # Gfriends keys sometimes include the extension already as the dict key stem.jpg
        if name in mapping:
            return mapping[name]
    # try keys that are exactly name.jpg style already handled; also bare name.png in map
    for key, value in mapping.items():
        stem = Path(key).stem
        if stem == name:
            return value
    return None


def _download_bytes(url_or_path: str, proxy: str | None) -> bytes | None:
    if url_or_path.startswith(("http://", "https://")):
        opener = _opener(proxy)
        request = urllib.request.Request(url_or_path, headers={"User-Agent": "MovieScraper/1.0"})
        try:
            with opener.open(request, timeout=60) as response:
                return response.read(8_000_000)
        except Exception:
            return None
    path = Path(url_or_path)
    if path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            return None
    return None


def _upload_primary(
    server_type: str,
    base: str,
    actor_id: str,
    api_key: str,
    image: bytes,
    content_type: str,
    proxy: str | None,
) -> tuple[bool, str]:
    endpoint = _primary_image_url(server_type, base, actor_id, api_key)
    opener = _opener(proxy)
    # Emby accepts raw image bytes; also try base64 if raw fails.
    for payload, label in ((image, "raw"), (base64.b64encode(image), "base64")):
        request = urllib.request.Request(
            endpoint,
            data=payload,
            method="POST",
            headers={"Content-Type": content_type, "Accept": "*/*"},
        )
        try:
            with opener.open(request, timeout=60) as response:
                status = int(getattr(response, "status", 200) or 200)
            if status < 400:
                return True, label
        except urllib.error.HTTPError as exc:
            if label == "raw" and exc.code in {400, 415}:
                continue
            return False, f"HTTP {exc.code}"
        except Exception as exc:
            if label == "raw":
                continue
            return False, str(exc)
    return False, "上传失败"


def fill_missing_avatars(
    *,
    server_type: str,
    url: str,
    api_key: str,
    user_id: str = "",
    source: str = "gfriends",
    local_dir: str = "",
    proxy: str | None = None,
    cache_dir: Path | None = None,
    stop_check: StopFn | None = None,
    log: LogFn | None = None,
) -> None:
    """List persons missing Primary image and upload from Gfriends or local folder."""

    def _log(message: str) -> None:
        if log:
            log(message)

    def _stop() -> bool:
        return bool(stop_check and stop_check())

    server_type = "jellyfin" if server_type == "jellyfin" else "emby"
    label = "Jellyfin" if server_type == "jellyfin" else "Emby"
    ok, message = test_connection(server_type, url, api_key, user_id, proxy)
    _log(message)
    if not ok:
        return

    persons = _list_persons(server_type, url, api_key, user_id, proxy, _log)
    _log(f"{label} 演员列表: {len(persons)} 人")
    if source == "local":
        mapping = _load_local_map(local_dir, _log)
    else:
        mapping = _load_gfriends_map(proxy, _log, cache_dir=cache_dir)
    if not mapping:
        _log("头像来源为空，已停止补全")
        return

    success = fail = skip = 0
    for index, person in enumerate(persons, start=1):
        if _stop():
            _log("已停止演员头像补全")
            break
        name = str(person.get("Name") or "").strip()
        actor_id = str(person.get("Id") or "").strip()
        if not name or not actor_id:
            skip += 1
            continue
        tags = person.get("ImageTags")
        has_primary = isinstance(tags, dict) and bool(tags.get("Primary"))
        if has_primary:
            skip += 1
            continue
        found = _lookup_avatar(name, mapping)
        if not found:
            _log(f"[{index}/{len(persons)}] 未找到头像: {name}")
            fail += 1
            continue
        data = _download_bytes(found, proxy)
        if not data:
            _log(f"[{index}/{len(persons)}] 下载失败: {name}")
            fail += 1
            continue
        lower = found.lower()
        if lower.endswith(".png"):
            content_type = "image/png"
        elif lower.endswith(".webp"):
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"
        uploaded, detail = _upload_primary(server_type, url, actor_id, api_key, data, content_type, proxy)
        if uploaded:
            _log(f"[{index}/{len(persons)}] 已上传头像: {name} ({detail})")
            success += 1
        else:
            _log(f"[{index}/{len(persons)}] 上传失败: {name} ({detail})")
            fail += 1
    _log(f"演员头像补全结束：成功 {success}，失败 {fail}，跳过 {skip}")
