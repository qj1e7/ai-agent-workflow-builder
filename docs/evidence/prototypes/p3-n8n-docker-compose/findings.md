# n8n 2.42.6 in Docker Compose with PostgreSQL (THROWAWAY prototype)

Path: docs/evidence/prototypes/p3-n8n-docker-compose/findings.md
Raw evidence files in the same folder: d1_*.txt, d2_*.txt, d3_raw.txt, d4a_raw.txt, d4b_raw.txt, d5_raw.txt, d6_stublog.txt

Images: n8nio/n8n:2.42.6 (reports Version: 2.42.6), postgres:17, python:3.12-slim (Python 3.12.15). Docker Engine on macOS. Single runs, mock services, observed not inferred.

## Final compose.yaml
```yaml
name: protodocker
services:
  postgres:
    image: postgres:17
    environment: {POSTGRES_USER: n8n, POSTGRES_PASSWORD: ${PROTO_DB_PASSWORD}, POSTGRES_DB: n8n}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL","pg_isready -U n8n -d n8n"]
      interval: 3s
      timeout: 3s
      retries: 20
  n8n:
    image: n8nio/n8n:2.42.6
    depends_on: {postgres: {condition: service_healthy}}
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: postgres
      DB_POSTGRESDB_PORT: "5432"
      DB_POSTGRESDB_DATABASE: n8n
      DB_POSTGRESDB_USER: n8n
      DB_POSTGRESDB_PASSWORD: ${PROTO_DB_PASSWORD}
      WEBHOOK_URL: http://n8n:5678/
      N8N_DIAGNOSTICS_ENABLED: "false"
      N8N_VERSION_NOTIFICATIONS_ENABLED: "false"
      N8N_SECURE_COOKIE: "false"
      N8N_ENCRYPTION_KEY: ${PROTO_ENCRYPTION_KEY}
    ports: ["5679:5678"]
    volumes: [n8ndata:/home/node/.n8n]
    healthcheck:
      test: ["CMD-SHELL","wget -qO- http://localhost:5678/healthz || exit 1"]
      interval: 3s
      timeout: 3s
      retries: 40
  stub:
    image: python:3.12-slim
    command: ["python","-u","/app/stub.py"]
    volumes: ["./stub.py:/app/stub.py:ro"]
    ports: ["5691:5690"]
volumes: {pgdata: {}, n8ndata: {}}
```
Host ports: n8n 5679 (container 5678), stub 5691 (container 5690). The stub is bind-mounted from stub.py with host 127.0.0.1 changed to 0.0.0.0. gen.py: HTTP nodes call http://stub:5690, the error workflow calls http://localhost:5678/api/v1/executions/... from inside the n8n container. load.py unchanged except host port 5679.

Not in the brief but I added `N8N_ENCRYPTION_KEY` (fixed value). See implications.

## Setup that worked
1. `docker compose up -d`; n8n goes healthy about 25 s after start (postgres healthcheck first, then 148 tables and 286 migrations on first boot).
2. From the host: `POST /rest/owner/setup`, `POST /rest/login` (cookie), `POST /rest/api-keys` with scopes workflow read/list/create/update/activate/deactivate and execution read/list. Returned `rawApiKey`.
3. `python3 gen.py && python3 load.py`: three workflows created and activated through `/api/v1`. All HTTP 200.

Did not work / caveats:
- First attempt used postgres:16. It started, but n8n logged: `Postgres 16 is outside the supported range and receives compatibility support only. Upgrade to Postgres 17 or newer.` (d1_pg16_warning.txt). I tore it down and used 17 for everything else. Use 17.
- The container healthcheck uses `wget` against /healthz; that worked in the n8n image.
- Public-API activation response is very large (it echoes all nodes, including the API key in the error workflow). Do not log it.

## D1 Start on PostgreSQL in Compose: VERIFIED
Compose with DB_TYPE=postgresdb booted to healthy; log lines:
```
n8n-1  | Starting migration CreateMigrationFindingTables1790598807675
n8n-1  | Finished migration CreateMigrationFindingTables1790598807675
n8n-1  | Version: 2.42.6
n8n-1  | Editor is now accessible via:
```
Postgres: `select count(*) from migrations` = 286, last = CreateMigrationFindingTables1790598807675. `\dt` in the n8n database shows 148 tables (d1_tables.txt), for example:
```
 public | activity_event           | table | n8n
 public | agent_background_job     | table | n8n
 ...
 public | workflows_tags           | table | n8n
(148 rows)
```
Caveat: the startup log has no line that literally says "using postgres". The proof is the tables and migrations in Postgres, and the n8n data volume holds no SQLite file in use (I did not list it). With 16 it also started (with the warning above).

## D2 Webhook, approve via stub, one write: VERIFIED
Resume URL registered by n8n used the Compose name because of WEBHOOK_URL:
```
resume_url: http://n8n:5678/webhook-waiting/1?signature=<redacted-1>
```
Start from host: `HTTP/1.1 202 Accepted {"accepted":true,"request_id":"req-A1"}`. Stub (inside Compose) posted to that URL by name and got `{"n8n_status":200,"n8n_body":"{\"message\":\"Workflow was started\"}"}`. Events (container clock, UTC):
```
10:25:26.101 run_started
10:25:26.127 agent_done
10:25:26.164 awaiting_approval
10:25:28.232 run_finished_approved
```
Mock Jira writes: exactly one, `[{"request_id":"req-A1","approver":"alice","title":"New langgraph release","ts":"10:25:28.226"}]`.
Note: the host cannot use that URL as is (n8n is not resolvable from the host); I swapped to localhost:5679 for host-side tests.

## D3 Safety facts: VERIFIED (raw: d3_raw.txt)
```
## no signature        HTTP/1.1 401 Unauthorized  {"error":"Invalid token"}
## wrong signature     HTTP/1.1 401 Unauthorized  {"error":"Invalid token"}   (?signature=deadbeef)
## writes after bad attempts: only the earlier req-A1 write (no new write)
## valid resume via stub: n8n_status 200
## resume finished run  HTTP/1.1 409 Conflict  {"code":409,"message":"The execution \"2 has finished already."}
```
Final writes: req-A1 once, req-A2 once.

## D4 Restart while waiting: VERIFIED for both cases (raw: d4a_raw.txt, d4b_raw.txt)
### D4a `docker compose restart n8n`
Run req-R1 reached awaiting_approval (exec 3). Restart took about 3 s to healthy. On boot n8n logged:
```
[Recovery] Logs available, amended execution
Found unfinished executions: 3
This could be due to a crash of an active workflow or a restart of n8n
```
Resuming with the SAME saved URL (`/webhook-waiting/3?signature=<redacted-2>...`) returned 200, then `run_finished_approved` arrived and exactly one Jira write (`req-R1`, approver alice). The run was not lost.
### D4b `docker compose down` (volumes kept) then `up -d`
Run req-D1 (exec 4) waiting; URL saved. All containers and the network were removed, volumes `protodocker_n8ndata` and `protodocker_pgdata` stayed. After `up -d` and healthy, the stub had lost its in-memory map (`{}`), so I re-registered the same saved URL in the stub (test-harness step, not n8n). Resume with the same URL: 200, `run_finished_approved`, one write (`req-D1`). `GET /api/v1/executions` shows executions 1 to 4 all `success`.
Not tested: resuming while n8n is still booting, a waiting run across a volume delete, and n8n running as several replicas.

## D5 Error workflow by service name: VERIFIED (raw: d5_raw.txt)
Run req-E1 on the failing workflow (calls http://127.0.0.1:1/dead). Events:
```
10:26:26.599 run_started  (exec 5)
error_workflow_fired      (raw payload, execution.url = http://n8n:5678/workflow/GmfUsGDIE64MKwFU/executions/5)
10:26:26.684 error_recovered_request_id  request_id=req-E1 failed_node="Dead HTTP call"
           message="The service refused the connection - perhaps it is offline"
```
The error workflow reached the stub at http://stub:5690 and also called n8n's own API at http://localhost:5678 from inside the container to recover request_id. Note the execution.url in the payload uses the WEBHOOK_URL host (n8n:5678).

## D6 Rough timing, ROUGH, one run (stub clock, d6_stublog.txt)
- run_started to awaiting_approval: 10:25:26.101 to .164 = about 63 ms.
- Stub resume call at 10:25:28.140, n8n replied 200 at .190 (about 50 ms), finished event at .232, so about 92 ms from resume call to finish.
Mock services only, no real agent, Teams or Jira latency.

## Design implications (plain words)
- The Compose plan holds. n8n 2.42.6 runs on its own PostgreSQL, our services reach each other by name, and approvals work end to end.
- Use PostgreSQL 17 (or newer). 16 works but n8n warns that it is only compatibility support.
- A run waiting for approval survives an n8n restart and a full down/up, as long as the n8n database volume stays and the encryption key is the same. This is good for Azure Container Apps restarts. I set a fixed N8N_ENCRYPTION_KEY; I did not test whether the resume signature depends on it, so on Azure keep the key in Key Vault and never let it change. Treat that as an assumption to test before relying on it.
- Scale to zero: a waiting run does not need n8n to be running, but the resume call does. Our Agent API must wake n8n (or retry) when the Approver clicks. I did not test a resume sent while n8n is still starting. Keep min replicas at 1 for n8n, or add retry with a short delay.
- n8n logs "Found unfinished executions" after a restart. It is a warning; it did not stop the resume. Do not alert on it blindly.
- Two URL worlds: WEBHOOK_URL=http://n8n:5678/ makes resume URLs work inside the network only. For real use, the stored URL must be reachable from whoever calls it. Our Agent API should be the only caller and live inside the network, so this is fine. Anything external (Teams button) goes to our API, not to n8n. Production will need the public or internal base URL set to what our API can reach.
- Our own stub/Agent API must keep approval state in a database, not memory. The down/up test lost the stub map, which would lose every pending approval.
- The earlier findings still stand: the resume URL is a secret, n8n does not check who approves, so self-approval and two-approver rules live in our API.
- Workflows are loaded through the public API, not import with activeState. The owner and API key can be created over REST on a fresh instance, so setup can be scripted in CI.
