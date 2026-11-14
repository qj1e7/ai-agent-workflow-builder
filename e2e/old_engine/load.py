"""Loads the old-engine seed before bootstrap: the tables at their newest shape, then the rows a
platform from before E10 kept. It runs in the platform-api image, so it migrates with the
platform's own code. platform-api/tests/test_old_engine_seed.py writes the seed."""

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from platform_api.migrations import upgrade_all


def main(seed: Path) -> None:
    upgrade_all(os.environ["DATABASE_URL_OWNER"])
    tables = json.loads(seed.read_text())["tables"]
    with psycopg.connect(os.environ["DATABASE_URL_SEED"]) as conn:
        # As the superuser, so foreign keys wait until every row is in.
        conn.execute("SET session_replication_role = replica")
        for table in tables:
            schema, name = table["table"].split(".")
            columns = sql.SQL(", ").join(sql.Identifier(c) for c in table["columns"])
            into = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                sql.Identifier(schema), sql.Identifier(name), columns
            )
            with conn.cursor().copy(into) as copy:
                copy.write(table["data"])
        serials = conn.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns"
            " WHERE table_schema IN ('builder', 'orchestration', 'monitoring')"
            " AND column_default LIKE 'nextval%'"
        ).fetchall()
        for schema, name, column in serials:
            conn.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence({}, {}), coalesce(max({}), 0) + 1, false)"
                    " FROM {}.{}"
                ).format(
                    sql.Literal(f"{schema}.{name}"),
                    sql.Literal(column),
                    sql.Identifier(column),
                    sql.Identifier(schema),
                    sql.Identifier(name),
                )
            )
    print(f"seed: loaded {len(tables)} tables from {seed.name}", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
