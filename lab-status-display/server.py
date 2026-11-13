"""Run the lab display prototype on the Pi's own desktop."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
STATUS_OPTIONS = {
    "laser": ("unknown", "off", "on"),
    "lock": ("unknown", "unlocked", "locked"),
    "experiment": ("unknown", "idle", "running"),
}


class LabServer(ThreadingHTTPServer):
    def __init__(self, address):
        self.status = dict.fromkeys(STATUS_OPTIONS, "unknown")
        self.status_lock = Lock()
        super().__init__(address, LabHandler)


class LabHandler(BaseHTTPRequestHandler):
    def reply(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def reply_status(self, change=None):
        with self.server.status_lock:
            if change is not None:
                self.server.status.update(change)
            body = json.dumps(self.server.status).encode("utf-8")
        self.reply(200, "application/json", body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/status":
            self.reply_status()
            return
        if path not in ASSETS:
            self.send_error(404)
            return
        name, content_type = ASSETS[path]
        self.reply(200, content_type, (ROOT / name).read_bytes())

    def do_POST(self):
        if self.path != "/api/status":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 1 <= length <= 512:
                raise ValueError
            change = json.loads(self.rfile.read(length))
            if not isinstance(change, dict) or len(change) != 1:
                raise ValueError
            field, value = next(iter(change.items()))
            if value not in STATUS_OPTIONS.get(field, ()):
                raise ValueError
        except ValueError:
            self.send_error(400, "Invalid status change")
            return
        self.reply_status(change)

    def log_request(self, code="-", size="-"):
        if urlsplit(self.path).path != "/api/status" or str(code) != "200":
            super().log_request(code, size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with LabServer(("127.0.0.1", args.port)) as server:
        origin = f"http://127.0.0.1:{server.server_port}"
        print(f"Touch controller: {origin}/\nDoor display:     {origin}/?view=door", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
