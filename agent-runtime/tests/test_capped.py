"""Size limits, compression and the check's deadline for outside reads (capped.py, ADR 0025)."""

import gzip

import httpx
import pytest

from agent_runtime.capped import OutOfTime, TooLarge, deadline, read_capped, time_left


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def client(handle: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handle, timeout=15.0)


def test_the_answer_is_asked_for_uncompressed():
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"{}")

    assert read_capped(client(httpx.MockTransport(handle)), "GET", "https://a.test/", limit=10) == (
        200,
        b"{}",
    )
    assert seen[0].headers["accept-encoding"] == "identity"


def test_a_compressed_answer_is_refused_before_it_is_unpacked():
    """199 KB of gzip once unpacked to 142 MB against a 2 MB cap."""
    bomb = gzip.compress(b"0" * 1_000_000)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bomb, headers={"content-encoding": "gzip"})

    with pytest.raises(TooLarge):
        read_capped(client(httpx.MockTransport(handle)), "GET", "https://a.test/", limit=1000)


def test_outside_a_check_there_is_no_deadline():
    assert time_left() is None


def test_a_check_s_deadline_is_its_own_and_ends_with_it():
    clock = Clock()
    with deadline(40, clock):
        assert time_left() == 40
        clock.now += 15
        assert time_left() == 25
    assert time_left() is None


def test_a_read_after_the_deadline_is_not_made():
    clock = Clock()
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=b"{}")

    with deadline(40, clock):
        clock.now += 41
        with pytest.raises(OutOfTime):
            read_capped(client(httpx.MockTransport(handle)), "GET", "https://a.test/", limit=10)
    assert asked == []


def test_a_slow_answer_that_passes_the_deadline_is_dropped():
    """A fake NVD that takes its full 15 s, near the end of a check, can't add those 15 s."""
    clock = Clock()

    def handle(request: httpx.Request) -> httpx.Response:
        clock.now += 15
        return httpx.Response(200, content=b"{}")

    with deadline(40, clock):
        clock.now += 30
        with pytest.raises(OutOfTime):
            read_capped(client(httpx.MockTransport(handle)), "GET", "https://a.test/", limit=10)


def test_each_timeout_is_cut_to_the_time_left():
    clock = Clock()
    timeouts: list[dict[str, float]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, content=b"{}")

    with deadline(40, clock):
        clock.now += 34
        read_capped(client(httpx.MockTransport(handle)), "GET", "https://a.test/", limit=10)
    assert timeouts == [{"connect": 6.0, "read": 6.0, "write": 6.0, "pool": 6.0}]
