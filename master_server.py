#!/usr/bin/env python3
"""StatsBorg central ingest API and shared viewer.

Runs once on the control host. Per-box StatsBorg agents POST completed match
snapshots here; this service dedupes them into PostgreSQL and serves read APIs.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import store

MASTER_TOKEN = os.environ.get("MASTER_TOKEN", "")
PORT = int(os.environ.get("PORT", "8080"))
HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER_HTML = os.path.join(HERE, "pgcr_viewer.html")
MEDALS_DIR = os.path.join(HERE, "medals")


def log(message: str) -> None:
    print(f"[statsborg-master] {message}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        if not MASTER_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {MASTER_TOKEN}"

    def _read_json(self):
        size = int(self.headers.get("Content-Length", 0) or 0)
        if size <= 0:
            return None
        try:
            return json.loads(self.rfile.read(size))
        except ValueError:
            return None

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authed():
            return self._send_json({"error": "unauthorized"}, 401)

        if path == "/api/v1/matches":
            snapshot = self._read_json()
            if not isinstance(snapshot, dict) or not snapshot.get("fingerprint"):
                return self._send_json({"error": "invalid match payload"}, 400)
            try:
                imported = store.ingest_match(snapshot)
            except Exception as exc:
                log(f"ingest failed: {exc}")
                return self._send_json({"error": "ingest failed"}, 500)
            return self._send_json({
                "status": "imported" if imported else "duplicate",
                "fingerprint": snapshot["fingerprint"],
            })

        if path == "/api/v1/servers/heartbeat":
            body = self._read_json() or {}
            server_id = body.get("server_id") or self.headers.get("X-Server-Id")
            if not server_id:
                return self._send_json({"error": "missing server_id"}, 400)
            try:
                store.record_heartbeat(server_id, int(body.get("spool_backlog", 0) or 0))
            except Exception as exc:
                log(f"heartbeat failed: {exc}")
                return self._send_json({"error": "heartbeat failed"}, 500)
            return self._send_json({"status": "ok"})

        return self._send_json({"error": "not found"}, 404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html"):
                with open(VIEWER_HTML, "rb") as handle:
                    return self._send_bytes(handle.read(), "text/html; charset=utf-8")

            if path == "/healthz":
                return self._send_json({"status": "ok"})

            if path == "/api/v1/servers":
                return self._send_json(store.list_servers())

            if path == "/api/games":
                return self._send_json(store.get_all_games())

            if path.startswith("/api/games/"):
                game = store.get_game(path[len("/api/games/"):])
                return self._send_json(game) if game else self._send_json({"error": "not found"}, 404)

            if path.startswith("/history/"):
                game = store.get_game(path[len("/history/"):])
                return self._send_json(game) if game else self._send_json({"error": "not found"}, 404)

            if path == "/api/players":
                name = (query.get("name") or [None])[0]
                if name:
                    player = store.get_player(name)
                    return self._send_json(player) if player else self._send_json({"error": "not found"}, 404)
                return self._send_json(store.get_all_players())

            if path.startswith("/api/leaderboard/"):
                stat = path[len("/api/leaderboard/"):]
                limit = int((query.get("limit") or [25])[0])
                return self._send_json(store.get_leaderboard(stat, limit=limit))

            if path == "/api/pvp":
                player = (query.get("player") or [None])[0]
                if not player:
                    return self._send_json({"error": "missing player"}, 400)
                return self._send_json(store.get_pvp(player))

            if path.startswith("/medals/"):
                filename = os.path.basename(path[len("/medals/"):])
                filepath = os.path.join(MEDALS_DIR, filename)
                if not os.path.isfile(filepath):
                    return self._send_json({"error": "not found"}, 404)
                ctype = "image/svg+xml" if filename.endswith(".svg") else "image/gif"
                with open(filepath, "rb") as handle:
                    return self._send_bytes(handle.read(), ctype)

            return self._send_json({"error": "not found"}, 404)
        except Exception as exc:
            log(f"GET {path} failed: {exc}")
            return self._send_json({"error": "server error"}, 500)


def wait_for_schema() -> None:
    for attempt in range(1, 61):
        try:
            store.init_schema()
            log("schema ready")
            return
        except Exception as exc:
            log(f"waiting for database ({attempt}/60): {exc}")
            time.sleep(2)
    log("FATAL: database never became ready")
    sys.exit(1)


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        log("FATAL: DATABASE_URL is required")
        sys.exit(1)
    if not MASTER_TOKEN:
        log("WARNING: MASTER_TOKEN is empty; ingest is unauthenticated")
    wait_for_schema()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
