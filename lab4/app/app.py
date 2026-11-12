"""Run: python app.py. Open http://localhost:8000 (stdlib only)."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json
import urllib.request
import urllib.error
from qa_core import generate, AppError, MODEL

WEB = Path(__file__).resolve().parent / 'web'
PROXY = {'/v1/chat/completions', '/v1/models', '/api/show', '/api/ps', '/api/tags'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def proxy(self, body=None):
        req = urllib.request.Request('http://127.0.0.1:11434' + self.path,
            data=body, headers={'Content-Type': 'application/json'}, method=self.command)
        try:
            response = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as exc:
            self.send_json({'error': {'message': exc.read().decode('utf-8', errors='replace')}}, exc.code)
            return
        except (OSError, urllib.error.URLError):
            self.send_json({'error': {'message': 'Ollama не запущено або час очікування вичерпано.'}}, 502)
            return
        with response:
            self.send_response(200)
            self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                while True:
                    chunk = response.read1(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        self.close_connection = True

    def do_GET(self):
        if self.path in PROXY:
            return self.proxy()
        return super().do_GET()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                return self.send_json({'error': 'Неприпустимий розмір запиту.'}, 400)
            body = self.rfile.read(length)
            if self.path in PROXY:
                return self.proxy(body)
            if self.path != '/generate':
                return self.send_json({'error': 'Сторінку не знайдено.'}, 404)
            data = json.loads(body)
            if not isinstance(data, dict):
                raise AppError('Очікується JSON-об’єкт.')
            cards, raw, seconds = generate(data.get('text', ''), data.get('count', 4), data.get('model', MODEL))
            return self.send_json({'cards': cards, 'seconds': seconds, 'usage': raw.get('usage', {})})
        except (AppError, ValueError, TypeError) as exc:
            return self.send_json({'error': str(exc)}, 400)


if __name__ == '__main__':
    print('Картки: http://localhost:8000/\nBench: http://localhost:8000/bench.html', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
