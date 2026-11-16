-- Langfuse's role and database (ADR 0050). The db-init job runs this after db-init.sql only while
-- langfuse_enabled is true, so a deploy with Langfuse off runs exactly what it ran before.
SELECT 'CREATE ROLE langfuse LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'langfuse')
\gexec

ALTER ROLE langfuse LOGIN PASSWORD :'langfuse_pw';

GRANT langfuse TO CURRENT_USER;
ALTER DATABASE langfuse OWNER TO langfuse;
-- Langfuse expects UTC, and does not support another default.
ALTER DATABASE langfuse SET timezone TO 'UTC';

\connect langfuse
GRANT USAGE, CREATE ON SCHEMA public TO langfuse;
