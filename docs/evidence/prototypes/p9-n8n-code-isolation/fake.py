"""Stand-ins for spike P9, on port 42356 inside n8n's own network, as Azure's identity endpoint is.

- /msi/token stands in for the Container Apps identity endpoint. It records, per probe tag, whether a
  request came and whether its X-IDENTITY-HEADER equalled the identity header's canary. It never
  stores or prints the header.
- /v1/chat/completions stands in for a model, so n8n's AI Agent calls the Code Tool with no real model.
- /token and /api/echo stand in for a key's token endpoint and an API that uses the token, for the
  token-refresh check (refresh.py).
- /p9/record, /p9/reset and /p9/rotate are for run.py only.
"""

import json
import os
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HEADER = os.environ["P9_IDENTITY_HEADER"]
LOCK = threading.Lock()


def fresh():
    return {"identity": {}, "model_calls": 0, "tokens_issued": 0, "echo": [], "other_paths": {}}


STATE = {"record": fresh(), "token": 0, "stale": set()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return self.rfile.read(n) if n else b""

    def _route(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        body = self._body()
        if url.path == "/msi/token":
            tag = (query.get("p9probe") or ["untagged"])[0]
            ok = self.headers.get("X-IDENTITY-HEADER") == HEADER
            with LOCK:
                seen = STATE["record"]["identity"].setdefault(tag, {"requests": 0, "with_canary_header": 0})
                seen["requests"] += 1
                seen["with_canary_header"] += int(ok)
            if ok:
                return self._send(200, {"access_token": "p9-fake-access-token", "expires_in": "3600", "token_type": "Bearer"})
            return self._send(400, {"error": "invalid_request", "error_description": "no valid X-IDENTITY-HEADER"})
        if url.path.endswith("/chat/completions"):
            return self._model(json.loads(body or b"{}"))
        if url.path == "/token":
            with LOCK:
                STATE["token"] += 1
                STATE["record"]["tokens_issued"] += 1
                n = STATE["token"]
            return self._send(200, {"access_token": f"p9-fake-oauth-token-{n}", "token_type": "bearer", "expires_in": 3600})
        if url.path == "/api/echo":
            auth = self.headers.get("authorization") or ""
            current = f"Bearer p9-fake-oauth-token-{STATE['token']}"
            ok = STATE["token"] > 0 and auth == current and STATE["token"] not in STATE["stale"]
            with LOCK:
                STATE["record"]["echo"].append(200 if ok else 401)
            return self._send(200 if ok else 401, {"ok": ok})
        if url.path == "/p9/record":
            with LOCK:
                return self._send(200, STATE["record"])
        if url.path == "/p9/reset":
            with LOCK:
                STATE["record"] = fresh()
            return self._send(200, {"reset": True})
        if url.path == "/p9/rotate":
            with LOCK:
                STATE["stale"].add(STATE["token"])
            return self._send(200, {"rotated": True})
        with LOCK:
            other = STATE["record"]["other_paths"]
            other[url.path] = other.get(url.path, 0) + 1
        return self._send(404, {"error": "not found"})

    def _model(self, req):
        """Calls every tool it is offered once, then answers 'done'."""
        with LOCK:
            STATE["record"]["model_calls"] += 1
        answered = any(m.get("role") == "tool" for m in req.get("messages") or [])
        tools = [t["function"]["name"] for t in req.get("tools") or [] if t.get("type") == "function"]
        if answered or not tools:
            message = {"role": "assistant", "content": "done"}
            finish = "stop"
        else:
            calls = [
                {"id": f"call_p9_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps({"input": "run the probe"})}}
                for i, name in enumerate(tools)
            ]
            message = {"role": "assistant", "content": None, "tool_calls": calls}
            finish = "tool_calls"
        base = {"id": "p9", "created": int(time.time()), "model": req.get("model") or "p9-fake"}
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if not req.get("stream"):
            return self._send(200, {**base, "object": "chat.completion", "usage": usage,
                                    "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
        delta = dict(message)
        if "tool_calls" in delta:
            delta["tool_calls"] = [dict(c, index=i) for i, c in enumerate(delta["tool_calls"])]
        chunks = [
            {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
        ]
        data = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return self._send(200, data.encode(), "text/event-stream")

    do_GET = do_POST = do_PUT = _route


class DualStack(ThreadingHTTPServer):
    """Listens on IPv6 and IPv4, since n8n's Node resolves localhost to ::1 first."""

    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == "__main__":
    DualStack(("::", 42356), Handler).serve_forever()
