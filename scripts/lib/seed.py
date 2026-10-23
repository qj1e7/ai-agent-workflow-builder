"""Makes a use case and a run that waits at the approval gate, so a test has real ids.

Runs inside the platform-api container, which has python and reaches the API on localhost:
    docker compose exec -T platform-api python - ids < scripts/lib/seed.py
    docker compose exec -T platform-api python - openapi < scripts/lib/seed.py

`ids` prints {"use_case_id", "run_id", "approval_id"}. `openapi` prints the API's OpenAPI document
with those ids as the example value of each path parameter, so a scanner calls real resources.
`openapi-public` keeps only the /api/ routes, the ones the Portal's nginx publishes.
"""

import json
import sys
import time
import urllib.request
import uuid

BASE = "http://localhost:8000"
USER = "alice"


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


def seed() -> dict[str, str]:
    created = call(
        "POST",
        "/api/v1/use-cases",
        {
            "template": "release_check",
            "name": f"scan seed {uuid.uuid4().hex[:8]}",
            "instruction": (
                "Check langchain-ai/langgraph for new releases and open a ticket for the team."
            ),
            "params": {
                "repo": "langchain-ai/langgraph",
                "tag_pattern": r"^\d+\.\d+\.\d+$",
                "ticket_project": "MOCK",
                "last_seen_tag": "1.2.14",
            },
        },
    )
    use_case_id = created["use_case_id"]
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
            return {
                "use_case_id": use_case_id,
                "run_id": run_id,
                "approval_id": run["approval"]["approval_id"],
            }
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
