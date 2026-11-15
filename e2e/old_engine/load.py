"""Loads the old-engine seed before bootstrap: the tables at their newest shape, then the rows a
platform from before E10 kept. It runs in the platform-api image, so it migrates with the
platform's own code. platform-api/tests/test_old_engine_seed.py writes the seed.

Compose runs it again whenever it recreates the stack, as `compose run --build e2e` does after
`up`. By then the platform may have moved what it loaded, so a database that holds the seed's
workflows is left as it is."""

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
        if loaded_before(conn, tables):
            print(f"seed: {seed.name} is loaded already, so nothing changed", flush=True)
            return
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


def loaded_before(
    conn: psycopg.Connection[tuple[object, ...]], tables: list[dict[str, str]]
) -> bool:
    [use_cases] = [t for t in tables if t["table"] == "builder.use_cases"]
    ids = [line.split("\t", 1)[0] for line in use_cases["data"].splitlines()]
    row = conn.execute(
        "SELECT count(*) FROM builder.use_cases WHERE use_case_id = ANY(%s)", (ids,)
    ).fetchone()
    return row is not None and int(str(row[0])) > 0


if __name__ == "__main__":
    main(Path(sys.argv[1]))
