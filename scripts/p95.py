"""Times one route of the API, one request after another, and reports its percentiles.

Standard library only, so it also runs inside the platform-api container, which reaches the API
on localhost while a scan stack publishes no host ports:
    docker compose exec -T platform-api python - http://localhost:8000 GET /api/v1/runs \\
        /tmp/runs.json --count 500 --user alice < scripts/p95.py

A JSON body may hold {marker}, which becomes a new value on every request, because the model
gateway answers a repeated prompt from its store.

Only 2xx answers are timed. It exits 1 when any timed request failed.

With --stream it times the live stream instead. It opens the stream of a new run, then posts
--count agent events to that run, one each --interval seconds, signed with the callback key
(--signing-key, or CALLBACK_SIGNING_KEY). Each event's ts is the moment it was sent, and the
script subtracts it from the moment the event arrives on the stream. Run it inside the
platform-api container, so both times come from one clock and the key is in its environment:
    docker compose exec -T platform-api python - --stream http://localhost:8000 \\
        /tmp/stream.json --count 200 < scripts/p95.py

It exits 1 when an event was refused, lost, repeated or out of order.
"""

import argparse
import hashlib
import hmac
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def send(base_url: str, method: str, path: str, user: str, body: str | None) -> tuple[float, bool]:
    data = None if body is None else body.replace("{marker}", uuid.uuid4().hex).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "X-Dev-User": user,
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            ok = 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        error.read()
        ok = False
    except OSError:
        ok = False
    return (time.perf_counter() - started) * 1000, ok


def measure(
    base_url: str, method: str, path: str, count: int, user: str, body: str | None, warm_up: int
) -> dict[str, object]:
    for _ in range(warm_up):
        send(base_url, method, path, user, body)
    timings: list[float] = []
    for _ in range(count):
        elapsed, ok = send(base_url, method, path, user, body)
        if ok:
            timings.append(elapsed)
    return {
        "route": path,
        "method": method.upper(),
        "n": count,
        "errors": count - len(timings),
        "p50_ms": round(percentile(timings, 0.5), 1) if timings else None,
        "p95_ms": round(percentile(timings, 0.95), 1) if timings else None,
        "max_ms": round(max(timings), 1) if timings else None,
    }


class Arrivals:
    def __init__(self) -> None:
        self.seen: list[tuple[int, float]] = []
        self.changed = threading.Condition()

    def follow(self, response: Iterable[bytes], run_id: str, until: int) -> None:
        for raw in response:
            if len(self.seen) >= until:
                return
            line = raw.decode().rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            arrived = time.time()
            event = json.loads(line[len("data: ") :])
            if event["run_id"] != run_id:
                continue
            sent = datetime.fromisoformat(event["ts"]).timestamp()
            with self.changed:
                self.seen.append((event["seq"], (arrived - sent) * 1000))
                self.changed.notify_all()

    def wait_for(self, count: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self.changed:
            while len(self.seen) < count and time.monotonic() < deadline:
                self.changed.wait(max(0.0, deadline - time.monotonic()))


def signed(key: str, run_id: str, task_id: str) -> str:
    expires = int(time.time()) + 3600
    message = f"{run_id}|{task_id}|{expires}".encode()
    return f"{expires}.{hmac.new(key.encode(), message, hashlib.sha256).hexdigest()}"


def post_event(base_url: str, run_id: str, task_id: str, token: str, n: int) -> bool:
    body = {
        "task_id": task_id,
        "event": {
            "agent_seq": n,
            "ts": datetime.now(UTC).isoformat(),
            "agent": {"id": "p95_probe", "display": "Probe"},
            "summary": f"Probe event {n}.",
            "kind": "agent_step_started",
            "data": {"step": f"probe {n}"},
        },
    }
    task = urllib.parse.quote(task_id, safe="")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/internal/v1/runs/{run_id}/agent-events?task={task}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Callback-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            return response.status == 202
    except OSError:
        return False


def measure_stream(
    base_url: str, count: int, user: str, key: str, interval: float, warm_up: int
) -> dict[str, object]:
    run_id = f"run_p95{uuid.uuid4().hex[:16]}"
    task_id = f"{run_id}/work/1/1"
    token = signed(key, run_id, task_id)
    stream = urllib.request.urlopen(
        urllib.request.Request(
            f"{base_url.rstrip('/')}/api/v1/runs/{run_id}/events",
            headers={"Accept": "text/event-stream", "X-Dev-User": user},
        ),
        timeout=120,
    )
    total = warm_up + count
    arrivals = Arrivals()
    reader = threading.Thread(target=arrivals.follow, args=(stream, run_id, total), daemon=True)
    reader.start()
    time.sleep(0.5)
    refused = 0
    for n in range(1, total + 1):
        if not post_event(base_url, run_id, task_id, token, n):
            refused += 1
        time.sleep(interval)
    arrivals.wait_for(total - refused, timeout=30)
    reader.join(timeout=2)
    if not reader.is_alive():
        stream.close()
    seqs = [seq for seq, _ in arrivals.seen]
    timings = [ms for seq, ms in arrivals.seen if seq > warm_up]
    in_order = seqs == sorted(set(seqs))
    lost = total - len(set(seqs))
    return {
        "mode": "stream",
        "run_id": run_id,
        "n": count,
        "interval_s": interval,
        "warm_up": warm_up,
        "refused": refused,
        "lost": lost,
        "repeated": len(seqs) - len(set(seqs)),
        "in_order": in_order,
        "errors": refused + lost + (len(seqs) - len(set(seqs))) + (0 if in_order else 1),
        "p50_ms": round(percentile(timings, 0.5), 1) if timings else None,
        "p95_ms": round(percentile(timings, 0.95), 1) if timings else None,
        "max_ms": round(max(timings), 1) if timings else None,
    }


def stream_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Times event arrival on the live stream.")
    parser.add_argument("--stream", action="store_true", required=True)
    parser.add_argument("base_url")
    parser.add_argument("out", help="where the JSON result is written")
    parser.add_argument("--count", type=int, default=200, help="events to time (default 200)")
    parser.add_argument("--user", default="alice", help="the X-Dev-User header (default alice)")
    parser.add_argument("--interval", type=float, default=0.05, help="seconds between events")
    parser.add_argument("--warm-up", type=int, default=5, help="untimed events sent first")
    parser.add_argument("--signing-key", default=os.environ.get("CALLBACK_SIGNING_KEY"))
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")
    if not args.signing_key:
        parser.error("--signing-key or CALLBACK_SIGNING_KEY is needed to sign agent events")
    result = measure_stream(
        args.base_url, args.count, args.user, args.signing_key, args.interval, args.warm_up
    )
    return write(result, args.out)


def write(result: dict[str, object], out: str) -> int:
    text = json.dumps(result)
    with open(out, "w") as file:
        file.write(text + "\n")
    print(text)
    if result["errors"]:
        print(f"{result['errors']} errors", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str]) -> int:
    if "--stream" in argv:
        return stream_main(argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base_url")
    parser.add_argument("method")
    parser.add_argument("path")
    parser.add_argument("out", help="where the JSON result is written")
    parser.add_argument("--count", type=int, default=100, help="requests to time (default 100)")
    parser.add_argument("--user", default="alice", help="the X-Dev-User header (default alice)")
    parser.add_argument("--body", help="a JSON body; {marker} becomes a new value per request")
    parser.add_argument("--warm-up", type=int, default=0, help="untimed requests sent first")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")
    result = measure(
        args.base_url, args.method, args.path, args.count, args.user, args.body, args.warm_up
    )
    return write(result, args.out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
