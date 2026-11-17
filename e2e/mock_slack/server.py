"""Slack's Web API, as n8n's own Slack block and the platform call it (ADR 0045, ENGINE-PLAN E16).

n8n's Slack block always calls https://slack.com/api, so the e2e stack names this container
slack.com and n8n trusts the certificate authority it makes at start, which it writes to /ca for
n8n to read. The platform asks Slack what a key may do over plain HTTP on 8500, where the tests
also read every message a block sent, with the key it sent it with.

The key the stack gives the platform posts and reads the channel list. Every other key is
refused, as Slack refuses one it does not know.
"""

import json
import os
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

TOKEN = "mock-slack-token"
"""The stack's own test key, not a secret."""
SCOPES = "chat:write,channels:read"
HOST = "slack.com"
CA_DIR = Path(os.environ.get("CA_DIR", "/ca"))
KEYS_DIR = Path(os.environ.get("KEYS_DIR", "/tmp/mock-slack"))
SENT = frozenset({"chat.postMessage", "chat.update", "chat.delete", "chat.postEphemeral"})
CHANNELS = [
    {"id": "C0SUPPORT", "name": "support", "is_member": True},
    {"id": "C0HOUSE", "name": "eng-housekeeping", "is_member": True},
    {"id": "C0RANDOM", "name": "random", "is_member": False},
]
"""The channels the stack's key can see. It is a member of the first two, so it posts there."""


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sent: list[dict[str, Any]] = []

    def record(self, method: str, token: str, body: dict[str, Any]) -> None:
        with self.lock:
            self.sent.append({"method": method, "token": token, **body})


def certificates(ca_dir: Path, keys_dir: Path) -> tuple[Path, Path]:
    """A certificate authority, written to ca_dir/ca.pem for n8n to trust, and slack.com's
    certificate signed by it. Made fresh at each start, so nothing secret is kept anywhere."""
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "e2e mock Slack CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    keys_dir.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = keys_dir / "slack.pem", keys_dir / "slack.key"
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ca_dir.mkdir(parents=True, exist_ok=True)
    written = ca_dir / "ca.pem.part"
    written.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    written.replace(ca_dir / "ca.pem")
    return cert_path, key_path


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            if "json" in (self.headers.get("Content-Type") or ""):
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
            return {k: v[0] for k, v in parse_qs(raw.decode()).items()}

        def answer(self, method: str, body: dict[str, Any]) -> None:
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            if method in SENT:
                state.record(method, token, body)
            if token != TOKEN:
                self.send_json(200, {"ok": False, "error": "invalid_auth"})
                return
            match method:
                case "auth.test":
                    said = {"ok": True, "team": "Mock", "user": "platform", "user_id": "UBOT"}
                    self.send_json(200, said, {"x-oauth-scopes": SCOPES})
                case "conversations.list" if "private_channel" in str(body.get("types", "")):
                    # As Slack does: private channels need groups:read, which the key lacks.
                    error = {"ok": False, "error": "missing_scope", "needed": "groups:read"}
                    self.send_json(200, error)
                case "conversations.list":
                    self.send_json(200, {"ok": True, "channels": CHANNELS, "response_metadata": {}})
                case "users.profile.get":
                    self.send_json(200, {"ok": True, "profile": {"real_name": "Platform"}})
                case "chat.postMessage" | "chat.postEphemeral" | "chat.update" | "chat.delete":
                    channel = body.get("channel", "C0")
                    message = {"text": body.get("text", ""), "ts": "1763200000.000100"}
                    self.send_json(
                        200,
                        {"ok": True, "channel": channel, "ts": message["ts"], "message": message},
                    )
                case _:
                    self.send_json(200, {"ok": False, "error": "unknown_method"})

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/healthz":
                self.send_json(200, {"status": "ok"})
            elif url.path == "/_sent":
                with state.lock:
                    self.send_json(200, {"sent": list(state.sent)})
            elif url.path.startswith("/api/"):
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                self.answer(url.path.removeprefix("/api/"), query)
            else:
                self.send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                self.answer(url.path.removeprefix("/api/"), self.body())
            else:
                self.send_json(404, {"ok": False, "error": "not_found"})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def build_server(host: str, port: int, state: State) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(state))


def serve_tls(state: State, port: int, cert: Path, key: Path) -> ThreadingHTTPServer:
    httpd = build_server("0.0.0.0", port, state)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    return httpd


if __name__ == "__main__":
    shared = State()
    cert, key = certificates(CA_DIR, KEYS_DIR)
    tls = serve_tls(shared, int(os.environ.get("TLS_PORT", "443")), cert, key)
    threading.Thread(target=tls.serve_forever, daemon=True).start()
    build_server("0.0.0.0", int(os.environ.get("HTTP_PORT", "8500")), shared).serve_forever()
