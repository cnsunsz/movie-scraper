"""Optional browser UI, used only when app.py is started with --web."""

from __future__ import annotations

import json
import threading
import urllib.parse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import default_config, load_config, run_job

HOST = "127.0.0.1"
PORTS = range(8765, 8771)

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>电影元数据刮削</title>
<style>
  body { font-family: "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif;
         margin: 0; background: #f4f1ea; color: #1c1915; }
  main { max-width: 880px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 1.4rem; margin: 0 0 8px; }
  p.note { margin: 0 0 16px; color: #5c564c; font-size: 0.92rem; }
  form, section { background: #fff; border: 1px solid #e3dccf; border-radius: 10px;
                  padding: 16px; margin-bottom: 12px; }
  label.row { display: block; margin: 10px 0; }
  label.row span { display: block; font-weight: 600; margin-bottom: 4px; }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 8px 10px;
                     border: 1px solid #cfc6b8; border-radius: 6px; font-size: 1rem; }
  .modes label, .sources label { display: block; margin: 4px 0; font-weight: 400; }
  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  button { padding: 8px 16px; border-radius: 6px; border: 1px solid #1c1915;
           background: #1c1915; color: #fff; font-size: 1rem; cursor: pointer; }
  button.secondary { background: #fff; color: #1c1915; }
  button:disabled { opacity: 0.45; cursor: default; }
  #message { color: #8a2b12; min-height: 1.2em; }
  #progress { font-variant-numeric: tabular-nums; }
  #log { white-space: pre-wrap; background: #1c1915; color: #f4f1ea; min-height: 220px;
         max-height: 420px; overflow: auto; padding: 12px; border-radius: 8px;
         font-family: ui-monospace, monospace; font-size: 0.88rem; }
</style>
</head>
<body>
<main>
  <h1>电影元数据刮削</h1>
  <p class="note">路径是运行本程序的这台电脑上的目录。旁边模式不移动视频；文件夹模式会改名并移动。不删除原视频。按文件名番号 / 标题始终在本地解析。</p>
  <form id="job">
    <label class="row"><span>媒体目录</span>
      <input type="text" name="media_dir" value="__MEDIA__" autocomplete="off" placeholder="/path/to/videos">
    </label>
    <div class="modes">
      <strong>输出方式</strong>
      <label><input type="radio" name="output_mode" value="beside" __BESIDE__> 只在视频旁边写 nfo 和封面</label>
      <label><input type="radio" name="output_mode" value="folder" __FOLDER__> 按演员/番号改名并移动到输出目录</label>
    </div>
    <label class="row" id="output-row"><span>输出目录</span>
      <input type="text" name="output_dir" value="__OUTPUT__" autocomplete="off" placeholder="仅移动模式需要">
    </label>
    <div class="sources">
      <label><input type="checkbox" name="imdb" value="1" __IMDB__> IMDb（可选）</label>
    </div>
    <div class="actions">
      <button type="button" id="start">开始</button>
      <button type="button" id="stop" class="secondary">停止</button>
      <span id="progress">进度: 0 / 0</span>
    </div>
    <p id="message"></p>
  </form>
  <section>
    <strong>日志</strong>
    <div id="log"></div>
  </section>
</main>
<script>
const form = document.getElementById("job");
const outputRow = document.getElementById("output-row");
function syncMode() {
  const mode = form.output_mode.value;
  outputRow.style.display = mode === "folder" ? "" : "none";
}
form.querySelectorAll('input[name="output_mode"]').forEach(function (el) {
  el.addEventListener("change", syncMode);
});
syncMode();

function showMessage(text) {
  document.getElementById("message").textContent = text || "";
}

async function post(url) {
  const body = new URLSearchParams(new FormData(form));
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: url === "/start" ? body : ""
  });
  const data = await response.json();
  showMessage(data.message || "");
  poll();
}

document.getElementById("start").addEventListener("click", function () { post("/start"); });
document.getElementById("stop").addEventListener("click", function () { post("/stop"); });

async function poll() {
  try {
    const data = await (await fetch("/status")).json();
    const log = document.getElementById("log");
    log.textContent = data.log || "";
    log.scrollTop = log.scrollHeight;
    const name = data.name ? "  " + data.name : "";
    document.getElementById("progress").textContent =
      "进度: " + (data.current || 0) + " / " + (data.total || 0) + name;
    document.getElementById("start").disabled = !!data.running;
  } catch (err) {
    showMessage("无法读取状态");
  }
}
poll();
setInterval(poll, 1000);
</script>
</body>
</html>
"""


class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.stop = threading.Event()
        self.logs: list[str] = []
        self.current = 0
        self.total = 0
        self.file_name = ""
        self.message = ""


JOB = Job()


def _log(message: str) -> None:
    with JOB.lock:
        JOB.logs.append(message)
        if len(JOB.logs) > 400:
            del JOB.logs[:-400]


def _progress(index: int, total: int, name: str) -> None:
    with JOB.lock:
        JOB.current = index
        JOB.total = total
        JOB.file_name = name


def _snapshot() -> dict:
    with JOB.lock:
        return {
            "running": JOB.running,
            "current": JOB.current,
            "total": JOB.total,
            "name": JOB.file_name,
            "log": "\n".join(JOB.logs),
            "message": JOB.message,
        }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "on", "true", "yes"}


def start_job(fields: dict[str, str]) -> tuple[bool, str, int]:
    media = (fields.get("media_dir") or "").strip()
    output = (fields.get("output_dir") or "").strip()
    mode = (fields.get("output_mode") or "beside").strip()
    use_imdb = _truthy(fields.get("imdb") or "")
    if not media:
        return False, "请填写媒体目录", 400
    if not Path(media).is_dir():
        return False, f"媒体目录不存在: {media}", 400
    if mode not in {"beside", "folder"}:
        return False, "输出方式无效", 400
    if mode == "folder" and not output:
        return False, "移动模式请填写输出目录", 400

    with JOB.lock:
        if JOB.running:
            return False, "已有任务正在运行，请先停止或等待结束", 409
        JOB.running = True
        JOB.stop.clear()
        JOB.logs = []
        JOB.current = 0
        JOB.total = 0
        JOB.file_name = ""
        JOB.message = "已开始"

    settings = {
        "media_dir": media,
        "output_dir": output,
        "output_mode": mode,
        "imdb": use_imdb,
    }
    try:
        # GUI/web no longer auto-writes config.json beside the app
    except OSError as exc:
        _log(f"无法保存 config.json: {exc}")

    def target() -> None:
        try:
            run_job(settings, JOB.stop.is_set, _log, _progress)
        except Exception as exc:
            _log(f"错误: {exc}")
        finally:
            with JOB.lock:
                JOB.running = False
                JOB.message = "已结束"

    threading.Thread(target=target, name="scrape", daemon=True).start()
    return True, "已开始", 200


def stop_job() -> tuple[bool, str, int]:
    with JOB.lock:
        running = JOB.running
        if running:
            JOB.stop.set()
            JOB.message = "正在停止，将在当前文件结束后停下"
    if not running:
        return False, "当前没有正在运行的任务", 400
    _log("正在停止，将在当前文件结束后停下")
    return True, "正在停止，将在当前文件结束后停下", 200


def render_page() -> str:
    config = load_config()
    mode = config.get("output_mode") or "beside"
    return (
        PAGE.replace("__MEDIA__", escape(str(config.get("media_dir") or ""), quote=True))
        .replace("__OUTPUT__", escape(str(config.get("output_dir") or ""), quote=True))
        .replace("__BESIDE__", "checked" if mode != "folder" else "")
        .replace("__FOLDER__", "checked" if mode == "folder" else "")
        .replace(
        "__IMDB__",
        "checked"
        if next(
            (item.get("enabled") for item in (config.get("sites") or []) if isinstance(item, dict) and item.get("name") == "imdb"),
            True,
        )
        else "",
    )
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "MovieScraper/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self._send(200, render_page(), "text/html; charset=utf-8")
            return
        if path == "/status":
            self._send(200, json.dumps(_snapshot(), ensure_ascii=False), "application/json; charset=utf-8")
            return
        self._send(404, "未找到", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path == "/start":
            ok, message, code = start_job(self._form())
        elif path == "/stop":
            ok, message, code = stop_job()
        else:
            self._send(404, json.dumps({"ok": False, "message": "未找到"}, ensure_ascii=False), "application/json; charset=utf-8")
            return
        body = json.dumps({"ok": ok, "message": message}, ensure_ascii=False)
        self._send(code, body, "application/json; charset=utf-8")

    def _form(self) -> dict[str, str]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length < 0 or length > 65536:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _send(self, code: int, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve() -> int:
    last_error: OSError | None = None
    httpd: Server | None = None
    port = 0
    for candidate in PORTS:
        try:
            httpd = Server((HOST, candidate), Handler)
            port = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        print(f"端口 8765–8770 都无法绑定: {last_error}", flush=True)
        return 1
    print(f"界面地址: http://{HOST}:{port}", flush=True)
    print("用浏览器打开上面的地址。按 Ctrl+C 结束。", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务", flush=True)
    finally:
        httpd.server_close()
    return 0
