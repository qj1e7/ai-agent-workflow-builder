#!/bin/sh
# Runs once, when the data volume is empty.
set -eu

psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  -v n8n_pw="$N8N_DB_PASSWORD" \
  -v owner_pw="$WAB_OWNER_PASSWORD" \
  -v builder_pw="$WAB_BUILDER_PASSWORD" \
  -v orchestration_pw="$WAB_ORCHESTRATION_PASSWORD" \
  -v monitoring_pw="$WAB_MONITORING_PASSWORD" <<'SQL'
CREATE ROLE n8n LOGIN PASSWORD :'n8n_pw';
CREATE DATABASE n8n OWNER n8n;

CREATE ROLE wab_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE wab_builder LOGIN PASSWORD :'builder_pw';
CREATE ROLE wab_orchestration LOGIN PASSWORD :'orchestration_pw';
CREATE ROLE wab_monitoring LOGIN PASSWORD :'monitoring_pw';
CREATE DATABASE platform OWNER wab_owner;
SQL
