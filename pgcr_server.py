"""Serve the PGCR viewer with auto-discovery of history files.

Usage: python pgcr_server.py [port]        (default: 8080)
"""
import glob
import json
import os
import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(ROOT, "history")
VIEWER_PATH = os.path.join(ROOT, "pgcr_viewer.html")


class PGCRHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            with open(VIEWER_PATH, "rb") as f:
                self.wfile.write(f.read())
        elif self.path == "/api/games":
            self._serve_game_list()
        elif self.path.startswith("/history/") or self.path.startswith("/medals/"):
            super().do_GET()
        else:
            self.send_error(404)

    def _serve_game_list(self):
        games = []
        for path in sorted(glob.glob(os.path.join(HISTORY_DIR, "*.json")), reverse=True):
            try:
                with open(path) as f:
                    d = json.load(f)
                game_entry = {
                    "filename": os.path.basename(path),
                    "timestamp": d.get("timestamp", ""),
                    "gametype": d.get("gametype", "unknown"),
                    "player_count": d.get("player_count", 0),
                    "winner": "",
                }
                if d.get("teams"):
                    teams_sorted = sorted(d["teams"], key=lambda t: t.get("place", 99))
                    game_entry["teams"] = [
                        {"name": t.get("name", "?"), "score_string": t.get("score_string", "0"),
                         "team_id": t.get("team_id", 0)} for t in teams_sorted
                    ]
                elif d.get("players"):
                    p0 = d["players"][0]
                    game_entry["winner"] = f"{p0.get('name', '?')} ({p0.get('score_string', '?')})"
                games.append(game_entry)
            except (json.JSONDecodeError, KeyError):
                continue
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(games).encode())

    def log_message(self, fmt, *args):
        pass  # quiet


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("0.0.0.0", port), PGCRHandler)
    print(f"PGCR Viewer running at http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
