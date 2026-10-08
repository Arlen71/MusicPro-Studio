"""Static server for the download page on Railway. No dependencies.

Listens on $PORT (set by Railway), adds cache and security headers, and answers
/healthz for the platform health check.
"""
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            body = b'ok'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        assets = self.path.startswith('/assets/')
        self.send_header('Cache-Control', 'public, max-age=86400' if assets else 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    print(f'MusicPro site on :{port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(ROOT))).serve_forever()
