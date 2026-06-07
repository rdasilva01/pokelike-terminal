"""
serve_local.py — Local HTTP server for pokelike-local/.

Serves static files with SPA fallback (unknown paths → index.html).
Run:    python serve_local.py
Browse: http://localhost:8080
"""
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
from pathlib import Path
from urllib.parse import unquote

PORT = 8080
ROOT = Path(__file__).parent / "pokelike-local"

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mpeg", ".mp3")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress per-request noise; log only 404s
        status = args[1] if len(args) > 1 else ""
        if status == "404":
            path = args[0].split()[1] if args else "?"
            print(f"  [404] {path}")

    def do_GET(self):
        path = unquote(self.path.split("?")[0].split("#")[0].lstrip("/")) or "index.html"
        file_path = ROOT / path

        # Directory → look for index.html inside it
        if file_path.is_dir():
            file_path = file_path / "index.html"

        # SPA fallback: any unknown path → root index.html
        if not file_path.exists():
            file_path = ROOT / "index.html"

        if not file_path.exists():
            self.send_error(404, "index.html not found — run download_site.py first")
            return

        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        body = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()


def main() -> None:
    if not ROOT.exists():
        print(f"[error] {ROOT} not found.")
        print("  Run:  python download_site.py  first.")
        return
    index = ROOT / "index.html"
    if not index.exists():
        print(f"[error] index.html not found in {ROOT}.")
        print("  Run:  python download_site.py  first.")
        return

    print(f"[serve] Root:  {ROOT}")
    print(f"[serve] URL:   http://localhost:{PORT}")
    print("[serve] Ctrl+C to stop\n")
    try:
        ThreadedHTTPServer(("", PORT), _Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] Stopped.")


if __name__ == "__main__":
    main()
