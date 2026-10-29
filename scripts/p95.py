"""Times one route of the API, one request after another, and reports its percentiles.

Standard library only, so it also runs inside the platform-api container, which reaches the API
on localhost while a scan stack publishes no host ports:
    docker compose exec -T platform-api python - http://localhost:8000 GET /api/v1/runs \\
        /tmp/runs.json --count 500 --user alice < scripts/p95.py

A JSON body may hold {marker}, which becomes a new value on every request, because the model
gateway answers a repeated prompt from its store. Warm-up requests are sent first and not timed.
Streaming (--stream) is not here yet.
"""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Sequence


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
    errors = 0
    for _ in range(count):
        elapsed, ok = send(base_url, method, path, user, body)
        timings.append(elapsed)
        errors += not ok
    return {
        "route": path,
        "method": method.upper(),
        "n": count,
        "errors": errors,
        "p50_ms": round(percentile(timings, 0.5), 1),
        "p95_ms": round(percentile(timings, 0.95), 1),
        "max_ms": round(max(timings), 1),
    }


def main(argv: Sequence[str]) -> int:
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
    text = json.dumps(result)
    with open(args.out, "w") as out:
        out.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
