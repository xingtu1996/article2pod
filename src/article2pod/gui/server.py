"""article2pod GUI —— 本地 Web 界面。

参考 book2vido GUI 架构（stdlib ThreadingHTTPServer，零依赖）：
  - 选文章（上传 / 本地路径）
  - 选音色（host / author 独立，12 个中文音色）
  - 选组合（5 组预置音色对）
  - 选语气（natural/lively/serious/cute/story，注入对话稿 prompt）
  - 生成（后台线程跑管线，前端轮询进度）→ 试听 / 下载 mp3+m4a

启动：
  python -m article2pod.gui [--port 8765]
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import llm, pipeline, tts
from ..config import DEFAULT_CONFIG, ROOT, load

GUI_DIR = Path(__file__).parent
UPLOAD_DIR = ROOT / "uploads"
OUT_ROOT = ROOT / "demo"

_jobs: dict = {}
_job_lock = threading.Lock()


# ── 后台任务 ──────────────────────────────────────────────


def _run_job(job_id: str, article_path: str, out_dir: str, opts: dict) -> None:
    """后台线程：捕获 pipeline 的 print 输出到 job.logs，更新进度。"""
    buf = StringIO()

    def log(msg: str):
        line = msg.rstrip()
        with _job_lock:
            _jobs[job_id]["logs"].append(line)
        buf.write(msg + "\n")

    def set_job(**kw):
        with _job_lock:
            _jobs[job_id].update(kw)

    set_job(step="对话稿生成中…", progress=15)
    try:
        # 把 pipeline 的 stdout 重定向到 job 日志
        class _Wrapped:
            def write(self, s): log(s); return len(s)
            def flush(self): pass
        old_stdout = sys.stdout
        sys.stdout = _Wrapped()
        try:
            stat = pipeline.run(
                article_path, out_dir, load(), no_tts=False,
                tone=opts.get("tone"), host_voice=opts.get("host_voice"),
                author_voice=opts.get("author_voice"),
            )
        finally:
            sys.stdout = old_stdout
        set_job(step="完成", progress=100, done=True, results=stat)
    except Exception as e:
        log(f"[error] {e}")
        set_job(step="失败", done=True, error=str(e))


# ── HTTP ──────────────────────────────────────────────────


class GuiHandler(BaseHTTPRequestHandler):
    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str):
        if not path.exists():
            self._json({"ok": False, "error": "not found"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass

    def do_GET(self):
        try:
            self._do_GET()
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            try:
                self._json({"ok": False, "error": str(e)}, 500)
            except Exception:
                pass

    def _do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._file(GUI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._file(GUI_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/style.css":
            self._file(GUI_DIR / "style.css", "text/css; charset=utf-8")
            return

        # 选项（音色/组合/语气/引擎）
        if path == "/api/options":
            self._json({
                "ok": True,
                "voices": tts.EDGE_VOICES,
                "presets": tts.VOICE_PRESETS,
                "tones": tts.TONES,
                "providers": tts.list_providers(),
            })
            return

        # 环境检查
        if path == "/api/check-env":
            self._json(self._check_env())
            return

        # 任务状态
        if path == "/api/status":
            qs = parse_qs(parsed.query)
            job_id = qs.get("job_id", [""])[0]
            with _job_lock:
                job = dict(_jobs.get(job_id, {}))
            self._json(job or {"ok": False, "error": "job not found"}, 404 if not job else 200)
            return

        # 成品列表（demo/out_* 下的 podcast.mp3/m4a + script.md）
        if path == "/api/history":
            items = []
            for d in sorted(OUT_ROOT.glob("out_*"), key=lambda p: p.stat().st_mtime, reverse=True):
                mp3 = d / "podcast.mp3"
                if not mp3.exists():
                    continue
                m4a = d / "podcast.m4a"
                script = d / "script.md"
                dur = 0.0
                try:
                    import subprocess
                    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                                        "-show_format", str(mp3)], capture_output=True, text=True, timeout=5)
                    dur = float(json.loads(r.stdout)["format"]["duration"])
                except Exception:
                    pass
                items.append({
                    "name": d.name,
                    "duration": round(dur, 1),
                    "size_kb": round(mp3.stat().st_size / 1024),
                    "mp3": f"/api/file?p={d.name}/podcast.mp3",
                    "m4a": f"/api/file?p={d.name}/podcast.m4a" if m4a.exists() else None,
                    "script": f"/api/file?p={d.name}/script.md" if script.exists() else None,
                    "modified": time.strftime("%m-%d %H:%M", time.localtime(mp3.stat().st_mtime)),
                })
            self._json({"ok": True, "items": items})
            return

        # 文件读取（仅限 OUT_ROOT 与 UPLOAD_DIR 内，防目录穿越）
        if path == "/api/file":
            qs = parse_qs(parsed.query)
            p = qs.get("p", [""])[0]
            rel = Path(p)
            if rel.is_absolute():
                self._json({"ok": False, "error": "absolute path not allowed"}, 400)
                return
            candidates = [OUT_ROOT / rel, UPLOAD_DIR / rel]
            for c in candidates:
                if c.exists():
                    ctype = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".md": "text/markdown; charset=utf-8",
                             ".json": "application/json"}.get(c.suffix, "application/octet-stream")
                    self._file(c, ctype)
                    return
            self._json({"ok": False, "error": "not found"}, 404)
            return

        self._json({"ok": False, "error": "not found"}, 404)

    def _check_env(self) -> dict:
        def has(cmd):
            import shutil
            return bool(shutil.which(cmd))

        def ollama_ok():
            try:
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
                return True
            except Exception:
                return False

        try:
            import edge_tts  # noqa: F401
            edge_ok = True
        except Exception:
            edge_ok = False
        return {
            "ok": True,
            "ollama": ollama_ok(),
            "ffmpeg": has("ffmpeg"),
            "edge_tts": edge_ok,
            "say": has("say"),
        }

    def do_POST(self):
        try:
            self._do_POST()
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            try:
                self._json({"ok": False, "error": str(e)}, 500)
            except Exception:
                pass

    def _do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 上传文章
        if path == "/api/upload":
            length = int(self.headers.get("Content-Length", 0))
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype:
                self._json({"ok": False, "error": "Expected multipart"})
                return
            boundary = ctype.split("boundary=")[1].strip('"')
            body = self.rfile.read(length)
            parts = body.split(b"--" + boundary.encode())
            fname, fdata = None, None
            for part in parts:
                if b'filename="' in part:
                    fs = part.index(b'filename="') + 10
                    fe = part.index(b'"', fs)
                    fname = part[fs:fe].decode("utf-8", errors="replace")
                    he = part.find(b"\r\n\r\n")
                    if he > 0:
                        fdata = part[he + 4:-2]
            if not fname or not fdata:
                self._json({"ok": False, "error": "No file found"})
                return
            safe = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", Path(fname).stem)[:60]
            UPLOAD_DIR.mkdir(exist_ok=True)
            save = UPLOAD_DIR / f"{safe}{Path(fname).suffix}"
            save.write_bytes(fdata)
            self._json({"ok": True, "path": str(save), "name": save.name})
            return

        # 生成
        if path == "/api/run":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            article_path = body.get("path", "")
            if not article_path or not Path(article_path).exists():
                self._json({"ok": False, "error": "请先选择或上传文章"})
                return
            preset = body.get("preset")
            host_v = body.get("host_voice") or None
            author_v = body.get("author_voice") or None
            if preset:
                for pr in tts.VOICE_PRESETS:
                    if pr["id"] == preset:
                        host_v = pr["host"]
                        author_v = pr["author"]
                        break
            tone = body.get("tone") or None
            name = Path(article_path).stem[:40]
            out_dir = OUT_ROOT / f"out_{name}"

            job_id = f"job_{int(time.time() * 1000)}"
            with _job_lock:
                _jobs[job_id] = {"progress": 0, "step": "排队中…", "logs": [],
                                 "done": False, "results": None, "error": None}
            t = threading.Thread(target=_run_job, args=(job_id, article_path, str(out_dir),
                                                        {"tone": tone, "host_voice": host_v,
                                                         "author_voice": author_v}),
                                 daemon=True)
            t.start()
            self._json({"ok": True, "job_id": job_id, "out_dir": str(out_dir)})
            return

        self._json({"ok": False, "error": "not found"}, 404)


def start_server(port: int = 8765, open_browser: bool = True):
    # 固定端口，占用则提示（不自动杀——article2pod 与 book2vido 可并存）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", port))
        s.close()
    except OSError:
        print(f"⚠️ 端口 {port} 已被占用。用 --port 换一个（如 8766）。")
        sys.exit(1)

    server = ThreadingHTTPServer(("127.0.0.1", port), GuiHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"article2pod GUI 运行中：{url}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser(description="article2pod GUI")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    start_server(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
