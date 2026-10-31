-- The Azure version of deploy/postgres/init.sh. It runs on every deploy, so each step converges.
SELECT format('CREATE ROLE %I LOGIN', role)
FROM unnest(ARRAY['n8n', 'wab_owner', 'wab_builder', 'wab_orchestration', 'wab_monitoring']) AS role
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role)
\gexec

ALTER ROLE n8n LOGIN PASSWORD :'n8n_pw';
ALTER ROLE wab_owner LOGIN PASSWORD :'owner_pw';
ALTER ROLE wab_builder LOGIN PASSWORD :'builder_pw';
ALTER ROLE wab_orchestration LOGIN PASSWORD :'orchestration_pw';
ALTER ROLE wab_monitoring LOGIN PASSWORD :'monitoring_pw';

-- The admin is not a superuser on Azure. It may hand a database to a role only while it is a member of that role.
GRANT n8n TO CURRENT_USER;
GRANT wab_owner TO CURRENT_USER;
ALTER DATABASE n8n OWNER TO n8n;
ALTER DATABASE platform OWNER TO wab_owner;

-- On Azure the public schema does not belong to the database's owner, so owning the database is
-- not enough for n8n to create its tables there.
\connect n8n
GRANT USAGE, CREATE ON SCHEMA public TO n8n;
