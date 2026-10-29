"""Makes sure a check of the Software watchlist waits at the approval gate, so a test has real ids.

Runs inside the platform-api container, which has python and reaches the API on localhost:
    docker compose exec -T platform-api python - ids < scripts/lib/seed.py
    docker compose exec -T platform-api python - openapi < scripts/lib/seed.py

`ids` prints {"use_case_id", "run_id", "approval_id"}. `openapi` prints the API's OpenAPI document
with those ids as the example value of each path parameter, so a scanner calls real resources.
`openapi-public` keeps only the /api/ routes, the ones the Portal's nginx publishes.

One watchlist per team: a run already waiting is reused, LangGraph already watched is fine, and
the schedule is turned off so a tick cannot start a second check. The software id stays out of
the ids, or a scanner would delete the watched software through the example value.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"
USER = "alice"
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}


def call(method: str, path: str, body: object = None, headers: dict[str, str] | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"X-Dev-User": USER, "Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def ids_of(use_case_id: str, run: dict) -> dict[str, str]:
    return {
        "use_case_id": use_case_id,
        "run_id": run["run_id"],
        "approval_id": run["approval"]["approval_id"],
    }


def seed() -> dict[str, str]:
    watchlist = call("GET", "/api/v1/watchlist")["watchlist"]
    last = None if watchlist is None else watchlist["last_check"]
    if last is not None and last["state"] == "awaiting_approval":
        return ids_of(watchlist["use_case_id"], call("GET", f"/api/v1/runs/{last['run_id']}"))
    try:
        watchlist = call("POST", "/api/v1/watchlist/software", LANGGRAPH)
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise
    use_case_id = watchlist["use_case_id"]
    call("DELETE", "/api/v1/watchlist/schedule")
    started = call(
        "POST",
        f"/api/v1/use-cases/{use_case_id}/runs",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    run_id = started["run_id"]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        run = call("GET", f"/api/v1/runs/{run_id}")
        if run["state"] == "awaiting_approval":
            return ids_of(use_case_id, run)
        if run["state"] in ("failed", "rejected", "succeeded"):
            raise SystemExit(f"seed run ended as {run['state']}")
        time.sleep(1)
    raise SystemExit("seed run never reached the approval gate")


def with_examples(spec: dict, ids: dict[str, str]) -> dict:
    wanted = {**ids}
    for path_item in spec["paths"].values():
        for operation in path_item.values():
            for parameter in operation.get("parameters", []):
                if parameter["in"] == "path" and parameter["name"] in wanted:
                    parameter["example"] = wanted[parameter["name"]]
    return spec


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "ids"
    ids = seed()
    if mode == "ids":
        print(json.dumps(ids))
    elif mode == "openapi":
        print(json.dumps(with_examples(call("GET", "/openapi.json"), ids)))
    elif mode == "openapi-public":
        spec = with_examples(call("GET", "/openapi.json"), ids)
        spec["paths"] = {
            path: item for path, item in spec["paths"].items() if path.startswith("/api/")
        }
        print(json.dumps(spec))
    else:
        raise SystemExit(f"unknown mode {mode!r}")


main()
