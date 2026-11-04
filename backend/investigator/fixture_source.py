"""Explicitly fictional HTTP evidence source for preview and wiring tests."""

import json
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def make_fixture_server(host="127.0.0.1", port=8091):
    path = Path(__file__).resolve().parents[2] / "scenarios" / "fixtures" / "payment-logs.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    created = time.time()
    timestamp = datetime.fromtimestamp(created, timezone.utc).isoformat()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                body, status = {"status": "ok", "mode": "fictional_fixture"}, 200
            elif parsed.path == "/evidence/logs":
                try:
                    params = parse_qs(parsed.query)
                    start = float(params.get("start", ["0"])[0])
                    end = float(params.get("end", [str(time.time())])[0])
                    service = params.get("service", ["payment"])[0]
                    records = [
                        {**r, "timestamp": timestamp}
                        for r in fixture["records"]
                        if r["service"] == service and start <= created <= end
                    ]
                    body, status = (
                        {"records": records, "truncated": False, "origin": "fixture"},
                        200,
                    )
                except ValueError:
                    body, status = {"error": "Invalid query"}, 400
            else:
                body, status = {"error": "Not found"}, 404
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    server = make_fixture_server(args.host, args.port)
    print(f"FICTIONAL fixture source on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
