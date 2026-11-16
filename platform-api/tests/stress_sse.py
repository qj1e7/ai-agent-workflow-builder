"""Temporary: SseConnection with the stress probe's timeline. Removed before the fix lands."""

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from starlette.types import Message, Receive, Scope, Send

from tests import stress_probe as probe
from tests.test_monitoring_http import SseConnection

_state: dict[str, Any] = {}


def begin(nodeid: str) -> None:
    probe.reset()
    _state.clear()
    _state.update(nodeid=nodeid, conns=0, latencies=[], max_lag=0.0, failed=False, cpu=probe.cpu())
    _state["wall"] = time.perf_counter()
    probe.mark(f"test begins: {nodeid}")


def end(nodeid: str) -> None:
    if not _state:
        return
    wall = time.perf_counter() - _state["wall"]
    used = probe.cpu() - _state["cpu"]
    latencies = " ".join(f"{t:.3f}" for t in _state["latencies"])
    worst_slow = max((took for _, took, _, _ in probe._slow), default=0.0)
    probe.out(
        f"STRESS {nodeid} failed={_state['failed']} starts=[{latencies}] "
        f"max_lag={_state['max_lag']:.3f} slow_callbacks={len(probe._slow)} "
        f"worst_slow={worst_slow:.2f} wall={wall:.2f} cpu={used:.2f}"
    )
    if (
        _state["failed"]
        or any(t > probe.SLOW * 2.5 for t in _state["latencies"])
        or worst_slow > probe.SLOW * 5
    ):
        probe.report(f"timeline of {nodeid}")


class ProbedSse(SseConnection):
    def __init__(self, app: FastAPI, path: str, headers: Mapping[str, str]) -> None:
        super().__init__(app, path, headers)
        probe.wrap_log(app.state.activity_log)
        _state["conns"] = _state.get("conns", 0) + 1
        self._n = _state["conns"]
        self._path = path
        self._first_body = True
        inner = self._app
        n = self._n

        async def entered(scope: Scope, receive: Receive, send: Send) -> None:
            probe.mark(f"conn {n} app task entered")
            await inner(scope, receive, send)

        self._app = entered  # type: ignore[assignment]

    async def __aenter__(self) -> SseConnection:
        probe.mark(f"conn {self._n} opens {self._path}")
        stats = {"max_lag": 0.0, "at": 0.0}
        lag = asyncio.create_task(probe.lag_monitor(stats))
        dog = asyncio.create_task(probe.watchdog(self._started))
        started = time.perf_counter()
        try:
            return await super().__aenter__()
        except BaseException as error:
            probe.mark(f"conn {self._n} FAILED to start: {error!r}; lag {stats}")
            _state["failed"] = True
            raise
        finally:
            _state["latencies"].append(time.perf_counter() - started)
            _state["max_lag"] = max(_state["max_lag"], stats["max_lag"])
            probe.mark(f"conn {self._n} enter done; max loop lag {stats}")
            lag.cancel()
            dog.cancel()

    async def _send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            probe.mark(f"conn {self._n} response start")
        elif self._first_body:
            self._first_body = False
            probe.mark(f"conn {self._n} first body {message.get('body', b'')[:40]!r}")
        await super()._send(message)
