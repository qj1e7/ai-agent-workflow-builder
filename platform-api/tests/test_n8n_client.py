import httpx
import pytest

from platform_api.orchestration.n8n import N8nClient, N8nError, OwnerOutcome


class FlakyN8n:
    """Answers like n8n whose database comes back after a few probes."""

    def __init__(self, not_ready_probes: int) -> None:
        self.not_ready_probes = not_ready_probes
        self.calls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        db_ready = len([c for c in self.calls if "/healthz/readiness" in c]) > self.not_ready_probes
        if request.url.path == "/healthz/readiness":
            return httpx.Response(
                200 if db_ready else 503, json={"status": "ok" if db_ready else "error"}
            )
        if request.url.path == "/rest/owner/setup":
            if not db_ready:
                return httpx.Response(503, json={"code": 503, "message": "Database is not ready!"})
            return httpx.Response(200, json={"data": {"id": "1"}})
        if request.url.path == "/rest/login":
            return httpx.Response(200, json={"data": {"id": "1"}})
        return httpx.Response(404)


def client(n8n: FlakyN8n) -> N8nClient:
    return N8nClient(
        "http://n8n:5678", transport=httpx.MockTransport(n8n.handle), sleep=lambda _: None
    )


def test_wait_healthy_needs_readiness_not_just_healthz():
    n8n = FlakyN8n(not_ready_probes=2)
    client(n8n).wait_healthy(timeout=30)
    assert n8n.calls.count("GET /healthz/readiness") == 3
    assert "GET /healthz" not in n8n.calls


def test_owner_setup_waits_out_a_lost_database():
    n8n = FlakyN8n(not_ready_probes=1)
    assert client(n8n).ensure_owner("owner@example.com", "Aa1secret") is OwnerOutcome.CREATED
    assert n8n.calls.count("POST /rest/owner/setup") == 2


def test_owner_setup_gives_up_when_the_database_stays_away():
    n8n = FlakyN8n(not_ready_probes=10**6)
    with pytest.raises(N8nError, match="did not get it back"):
        client(n8n).ensure_owner("owner@example.com", "Aa1secret", timeout=0)
