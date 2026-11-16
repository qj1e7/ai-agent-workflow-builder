#!/bin/sh
# Makes Langfuse's role and database, or brings an existing role's password up to date. Safe to run
# again. It runs before Langfuse starts, so a missing setting stops Langfuse with a plain reason.
set -eu

for name in LANGFUSE_DB_PASSWORD LANGFUSE_SALT LANGFUSE_ENCRYPTION_KEY LANGFUSE_NEXTAUTH_SECRET \
  LANGFUSE_CLICKHOUSE_PASSWORD LANGFUSE_VALKEY_PASSWORD; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "$name is empty. Run deploy/make-env.sh, which adds the Langfuse settings." >&2
    exit 1
  fi
done

psql -v ON_ERROR_STOP=1 --dbname postgres -v pw="$LANGFUSE_DB_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE langfuse LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'langfuse')
\gexec
ALTER ROLE langfuse PASSWORD :'pw';
SELECT 'CREATE DATABASE langfuse OWNER langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')
\gexec
-- Langfuse needs its database in UTC.
ALTER DATABASE langfuse SET timezone TO 'UTC';
SQL
