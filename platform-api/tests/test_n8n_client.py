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


class LimitedLogin:
    """Answers like n8n with an owner, whose sign-in is rate limited for the first few tries.
    n8n 2.42.6 answers 429 with Retry-After in seconds (express-rate-limit's default headers)."""

    def __init__(self, limited: int, retry_after: str | None = "7", status: int = 429) -> None:
        self.limited = limited
        self.retry_after = retry_after
        self.status = status
        self.logins = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/owner/setup":
            return httpx.Response(
                400, json={"code": 400, "message": "Instance owner already setup"}
            )
        if request.url.path == "/rest/login":
            self.logins += 1
            if self.logins <= self.limited:
                headers = {} if self.retry_after is None else {"Retry-After": self.retry_after}
                return httpx.Response(self.status, headers=headers, text="Too many requests")
            return httpx.Response(200, json={"data": {"id": "1"}})
        return httpx.Response(404)


def signing_in(n8n: LimitedLogin, slept: list[float]) -> N8nClient:
    return N8nClient(
        "http://n8n:5678", transport=httpx.MockTransport(n8n.handle), sleep=slept.append
    )


def test_sign_in_waits_out_a_rate_limit_for_as_long_as_n8n_says():
    n8n, slept = LimitedLogin(limited=2, retry_after="7"), []
    outcome = signing_in(n8n, slept).ensure_owner("owner@example.com", "Aa1secret")
    assert outcome is OwnerOutcome.SIGNED_IN
    assert slept == [7, 7]
    assert n8n.logins == 3


def test_sign_in_waits_a_short_default_when_n8n_names_no_time():
    n8n, slept = LimitedLogin(limited=1, retry_after=None), []
    signing_in(n8n, slept).ensure_owner("owner@example.com", "Aa1secret")
    assert slept == [10]


def test_sign_in_gives_up_after_three_minutes_of_rate_limits():
    n8n, slept = LimitedLogin(limited=10**6, retry_after="60"), []
    with pytest.raises(N8nError, match="still rate limited after 180s"):
        signing_in(n8n, slept).ensure_owner("owner@example.com", "Aa1secret")
    assert slept == [60, 60, 60]
    assert n8n.logins == 4


def test_a_retry_after_longer_than_the_time_left_is_cut_to_it():
    n8n, slept = LimitedLogin(limited=10**6, retry_after="300"), []
    with pytest.raises(N8nError, match="still rate limited"):
        signing_in(n8n, slept).ensure_owner("owner@example.com", "Aa1secret")
    assert slept == [180]
    assert n8n.logins == 2


def test_a_wrong_password_fails_at_once():
    n8n, slept = LimitedLogin(limited=10**6, status=401), []
    with pytest.raises(N8nError, match="could not sign in as owner@example.com: HTTP 401"):
        signing_in(n8n, slept).ensure_owner("owner@example.com", "Aa1secret")
    assert slept == []
    assert n8n.logins == 1
