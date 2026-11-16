"""Temporary instrumentation for the stream-start flake. Removed before the fix lands.

With STRESS_PROBE set, every SseConnection in tests/test_monitoring_http.py records a timeline:
when the app task first runs, when the response starts, each Cosmos DB and PostgreSQL read,
every event-loop callback slower than SLOW seconds (with the main thread's stack sampled while
it runs), each garbage collection over SLOW, and the await chain of every task if the response
has not started after WATCHDOG seconds."""

import asyncio
import gc
import os
import sys
import threading
import time
import traceback
from asyncio import events
from collections.abc import Awaitable, Callable
from typing import Any

SLOW = float(os.environ.get("STRESS_SLOW", "0.2"))
WATCHDOG = 4.0
ENABLED = bool(os.environ.get("STRESS_PROBE"))

_T0 = time.perf_counter()
_timeline: list[tuple[float, str]] = []
_slow: list[tuple[float, float, str, list[str]]] = []
_main = threading.get_ident()
_current: dict[str, Any] = {"start": None, "handle": None, "stacks": []}
_thread_lag = [0.0]


def out(line: str) -> None:
    stream = sys.__stderr__
    assert stream is not None
    stream.write(line + "\n")
    stream.flush()


def now() -> float:
    return time.perf_counter() - _T0


def mark(label: str) -> None:
    _timeline.append((now(), label))


def reset() -> None:
    _timeline.clear()
    _slow.clear()
    _thread_lag[0] = 0.0


def _describe(handle: Any) -> str:
    callback = getattr(handle, "_callback", None)
    owner = getattr(callback, "__self__", None)
    if isinstance(owner, asyncio.Task):
        return f"task {owner.get_name()} " + " > ".join(chain(owner.get_coro())[:6])
    return repr(handle)[:300]


def chain(coro: Any) -> list[str]:
    links: list[str] = []
    seen = 0
    while coro is not None and seen < 40:
        seen += 1
        frame = (
            getattr(coro, "cr_frame", None)
            or getattr(coro, "ag_frame", None)
            or getattr(coro, "gi_frame", None)
        )
        if frame is not None:
            name = frame.f_code.co_filename.rsplit("/", 2)
            links.append(f"{frame.f_code.co_qualname}@{'/'.join(name[-2:])}:{frame.f_lineno}")
        elif not hasattr(coro, "cr_await"):
            links.append(repr(coro)[:160])
            break
        coro = (
            getattr(coro, "cr_await", None)
            or getattr(coro, "ag_await", None)
            or getattr(coro, "gi_yieldfrom", None)
        )
    return links


def _install() -> None:
    original = events.Handle._run

    def timed(handle: Any) -> None:
        _current["start"] = time.perf_counter()
        _current["handle"] = handle
        _current["stacks"] = []
        try:
            original(handle)
        finally:
            took = time.perf_counter() - _current["start"]
            _current["start"] = None
            if took > SLOW:
                _slow.append((now() - took, took, _describe(handle), list(_current["stacks"])))

    events.Handle._run = timed  # type: ignore[method-assign]

    def sample() -> None:
        last = time.perf_counter()
        while True:
            time.sleep(0.02)
            t = time.perf_counter()
            _thread_lag[0] = max(_thread_lag[0], t - last - 0.02)
            last = t
            started = _current["start"]
            stacks: list[str] = _current["stacks"]
            if started is not None and t - started > SLOW * (len(stacks) + 1) and len(stacks) < 4:
                frame = sys._current_frames().get(_main)
                if frame is not None:
                    lines = traceback.format_stack(frame)[-14:]
                    stacks.append(f"after {t - started:.2f}s:\n" + "".join(lines))

    threading.Thread(target=sample, daemon=True, name="stress-probe").start()

    gc_start = [0.0]

    perf = time.perf_counter

    def on_gc(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            gc_start[0] = perf()
        else:
            took = perf() - gc_start[0]
            if took > SLOW:
                mark(f"gc gen {info.get('generation')} took {took:.2f}s")

    gc.callbacks.append(on_gc)


if ENABLED:
    _install()


def _pressure() -> str:
    parts: list[str] = []
    for kind in ("cpu", "io", "memory"):
        try:
            with open(f"/proc/pressure/{kind}") as f:
                some = f.readline().split()
            parts.append(f"{kind}:{some[1]}")
        except OSError:
            pass
    try:
        with open("/proc/loadavg") as f:
            parts.append("load:" + f.read().split()[0])
    except OSError:
        pass
    return " ".join(parts)


def _timed(label: str, fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        mark(f"{label} begin {args[1:] if len(args) > 1 else args}")
        started = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
        except BaseException as error:
            mark(f"{label} raised after {time.perf_counter() - started:.2f}s: {error!r}")
            raise
        size = len(result) if isinstance(result, list) else ""
        mark(f"{label} end after {time.perf_counter() - started:.2f}s {size}")
        return result

    return wrapper


def wrap_log(log: Any) -> None:
    if getattr(log, "_stress_wrapped", False):
        return
    log._stress_wrapped = True
    copy = getattr(log, "_copy", None)
    if copy is not None:
        copy.read_after = _timed("cosmos read_after", copy.read_after)
        copy.put = _timed("cosmos put", copy.put)
        copy.ensure = _timed("cosmos ensure", copy.ensure)
    log._postgres.read_after = _timed("pg read_after", log._postgres.read_after)
    status = getattr(log, "_status", None)
    if status is not None:
        original = log._copy_behind

        def behind() -> bool:
            value = original()
            if value:
                mark("copy behind")
            return value

        log._copy_behind = behind


async def lag_monitor(stats: dict[str, float]) -> None:
    loop = asyncio.get_running_loop()
    while True:
        t = loop.time()
        await asyncio.sleep(0.01)
        lag = loop.time() - t - 0.01
        if lag > stats["max_lag"]:
            stats["max_lag"] = lag
            stats["at"] = now()


async def watchdog(started: asyncio.Event) -> None:
    await asyncio.sleep(WATCHDOG)
    if started.is_set():
        return
    mark(f"WATCHDOG: no response start after {WATCHDOG}s; pressure {_pressure()}")
    for task in asyncio.all_tasks():
        mark(f"  task {task.get_name()}: " + " > ".join(chain(task.get_coro())))


def report(header: str) -> None:
    out(f"===== {header}")
    for t, label in sorted(_timeline):
        out(f"  {t:9.3f} {label}")
    for at, took, what, stacks in _slow:
        out(f"  SLOW CALLBACK at {at:9.3f} took {took:.2f}s: {what}")
        for stack in stacks:
            out("    " + stack.replace("\n", "\n    "))
    out(f"  max thread lag {_thread_lag[0]:.2f}s; pressure {_pressure()}")


def cpu() -> float:
    times = os.times()
    return times.user + times.system
