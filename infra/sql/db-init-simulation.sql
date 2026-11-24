-- The simulation's own PostgreSQL (ADR 0054) is a container that starts with no databases. The
-- sim-db-init job runs this, then db-init.sql, so each step converges.
SELECT 'CREATE DATABASE n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')
\gexec

SELECT 'CREATE DATABASE platform'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'platform')
\gexec
