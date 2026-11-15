"""Lists, read only, the runs still on the shared run workflow. From ENGINE-PLAN E11 its blocks
are off, and platform-api ends each of these as it starts, so a deploy is checked with this first.

    DATABASE_URL_OWNER=postgresql://... python -m platform_api.old_runs
"""

import os
import sys
from collections.abc import Mapping
from typing import Any

import psycopg

from platform_api.auth import ConfigError
from platform_api.orchestration.store import OLD_ENGINE_RUNS
from platform_api.settings import owner_database_url_from_env


def open_old_runs(owner_url: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(owner_url) as conn:
        conn.read_only = True
        found = conn.execute("SELECT to_regclass('orchestration.runs')").fetchone()
        if found is None or found[0] is None:
            return []
        return conn.execute(OLD_ENGINE_RUNS).fetchall()


def main(env: Mapping[str, str] | None = None) -> int:
    try:
        owner_url = owner_database_url_from_env(os.environ if env is None else env)
    except ConfigError as error:
        print(f"old runs: {error}", file=sys.stderr)
        return 2
    runs = open_old_runs(owner_url)
    for run_id, use_case_id, state, started_at in runs:
        print(f"{run_id}\t{use_case_id}\t{state}\tstarted {started_at.isoformat()}")
    print(f"{len(runs)} run(s) on the shared run workflow have not ended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
