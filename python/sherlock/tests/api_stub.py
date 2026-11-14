"""OpenAI-compatible /chat/completions stub for the G1 API scorer tests: no network beyond loopback.

`ChatStub(replies=[...])` answers every call with the next reply in `replies` (the last one repeats),
optionally with a non-200 status. It records every request body (`hits`, with the Authorization header
attached) so tests can assert the prompt carried no tools and no secrets.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        srv = self.server
        srv.hits.append({**body, "_auth": self.headers.get("Authorization")})
        i = min(len(srv.hits) - 1, len(srv.replies) - 1)
        reply, status = (srv.replies[i], srv.status) if isinstance(srv.replies[i], tuple) else (srv.replies[i], srv.status)
        if status != 200:
            out = json.dumps({"error": {"message": reply}}).encode()
            self.send_response(status)
        else:
            out = json.dumps({"id": "stub", "model": srv.model, "choices": [{"index": 0, "finish_reason": "stop",
                               "message": {"role": "assistant", "content": reply}}],
                              "usage": {"prompt_tokens": srv.usage[0], "completion_tokens": srv.usage[1]}}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class ChatStub:
    def __init__(self, replies=('{"needs_restore": "yes", "confidence": 90}',), usage=(10, 5), status=200, port=0,
                 model="stub"):
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self._srv.hits, self._srv.replies, self._srv.usage, self._srv.status, self._srv.model = \
            [], list(replies), usage, status, model
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}/v1"
        self.hits = self._srv.hits
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=5)
