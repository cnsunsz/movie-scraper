"""Small urllib helper shared by the metadata sources.

Socks proxies are rejected with a message. http and https proxies are applied
with ``ProxyHandler``. Timeouts and one retry live here.
"""

from __future__ import annotations

import urllib.error
import urllib.request

class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def classify_proxy(proxy: str | None) -> tuple[str | None, str | None]:
    """Return ``(proxy_url, warning)``.

    An empty value is ``(None, None)``. Socks is not supported by the
    standard library here: warning is set and the proxy is not used.
    """

    text = (proxy or "").strip()
    if not text:
        return None, None
    lowered = text.lower()
    if lowered.startswith("socks"):
        return None, "代理是 socks（标准库不能用），本次改为直接连接。请改成 http:// 或 https:// 代理。"
    if not lowered.startswith(("http://", "https://")):
        # Common "host:port" form from config edits; urllib needs a scheme.
        if "://" not in text and "/" not in text.split("@")[-1]:
            text = "http://" + text
            lowered = text.lower()
        else:
            return None, f"无法识别的代理地址（仅支持 http/https）: {text}"
    if not lowered.startswith(("http://", "https://")):
        return None, f"无法识别的代理地址（仅支持 http/https）: {text}"
    return text, None


def fetch(
    url: str,
    *,
    proxy: str | None = None,
    timeout: float = 20,
    headers: dict[str, str] | None = None,
    limit: int = 3_000_000,
    attempts: int = 2,
) -> tuple[int, bytes]:
    """GET ``url``. Return ``(status, body)``.

    ``attempts`` includes the first try, so 2 means one retry. HTTP 401/403/429
    are not retried.
    """

    proxy_url, warning = classify_proxy(proxy)
    if warning and (proxy or "").strip().lower().startswith("socks"):
        raise HttpError(warning)
    if warning and proxy_url is None and (proxy or "").strip():
        raise HttpError(warning)

    handlers: list = []
    if proxy_url:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers=headers or {})
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            with opener.open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                body = response.read(limit + 1)
            if len(body) > limit:
                raise HttpError("响应过大")
            return status, body
        except HttpError:
            raise
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            if status in {401, 403, 429}:
                raise HttpError(f"HTTP {status}", status=status) from exc
            last = exc
            if attempt + 1 >= attempts:
                raise HttpError(f"HTTP {status}", status=status) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise HttpError(str(last) if last else "请求失败")
