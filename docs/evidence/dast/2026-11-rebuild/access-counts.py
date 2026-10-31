"""Counts platform-api's access log lines in a DAST run's compose log, by route and answer.

usage: python3 -I access-counts.py <compose.log>

The compose log is what scripts/dast.sh's stack wrote to dast/out/compose.log. It holds every
request platform-api answered: the seeded run's own calls and every request ZAP sent, directly
and through the Portal's nginx.
"""

import re
import sys
from collections import Counter

ACCESS = re.compile(
    r"^platform-api-1\s+\| INFO:\s+\S+ - "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[0-9.]+" (?P<code>\d{3})'
)

ROUTES = [
    # Any method, and with a slash at the end too, as ZAP sends both.
    (
        "/api/v1/approvals/{approval_id}/decisions, any method",
        None,
        re.compile(r"^/api/v1/approvals/[^/?]+/decisions/?(\?.*)?$"),
    ),
    ("PUT /api/v1/settings/model", "PUT", re.compile(r"^/api/v1/settings/model(\?.*)?$")),
    ("GET /api/v1/people", "GET", re.compile(r"^/api/v1/people(\?.*)?$")),
    ("GET /api/v1/confirmations", "GET", re.compile(r"^/api/v1/confirmations(\?.*)?$")),
]
PEOPLE = re.compile(r"^/api/v1/(people|confirmations)(/|\?|$)")


def main(path: str) -> None:
    total = 0
    by_route: dict[str, Counter] = {name: Counter() for name, _, _ in ROUTES}
    people_writes: Counter = Counter()
    people_reads: Counter = Counter()
    with open(path, encoding="utf-8", errors="replace") as log:
        for line in log:
            hit = ACCESS.match(line)
            if not hit:
                continue
            total += 1
            method, route, code = hit["method"], hit["path"], hit["code"]
            for name, want, pattern in ROUTES:
                if want in (None, method) and pattern.match(route):
                    by_route[name][f"{method} {code}" if want is None else code] += 1
            if PEOPLE.match(route):
                (people_reads if method == "GET" else people_writes)[code] += 1
    print(f"platform-api requests answered: {total}")
    for name, counts in by_route.items():
        answers = ", ".join(f"{code} x{n}" for code, n in sorted(counts.items()))
        print(f"{name}: {sum(counts.values())} ({answers})")
    print(
        "People and confirmations, other than GET: "
        + ", ".join(f"{code} x{n}" for code, n in sorted(people_writes.items()))
    )
    print(
        "People and confirmations, GET (any path below them): "
        + ", ".join(f"{code} x{n}" for code, n in sorted(people_reads.items()))
    )


if __name__ == "__main__":
    main(sys.argv[1])
