# Install this bundle onto a machine as the live runtime at C:\n8n (scripts go flat, next to the compose file,
# because status.ps1 / backup.ps1 / set-code.mjs defaults assume that layout).
#   powershell -ExecutionPolicy Bypass -File .\unpack.ps1
# It never overwrites the n8n_data volume, so existing workflows and credentials survive.
$ErrorActionPreference = 'Stop'
$proj = $PSScriptRoot
$live = 'C:\n8n'

New-Item -ItemType Directory -Force -Path "$live\certs" | Out-Null
Copy-Item -LiteralPath "$proj\docker-compose.yml" -Destination "$live\docker-compose.yml" -Force
if (Test-Path -LiteralPath "$proj\certs\gateway-ca.pem") {
  Copy-Item -LiteralPath "$proj\certs\gateway-ca.pem" -Destination "$live\certs\gateway-ca.pem" -Force
  'installed gateway-ca.pem (ships with this bundle copy)'
} else {
  # No CA in the bundle (the normal case). A container configured with NODE_EXTRA_CA_CERTS
  # pointing at a missing file breaks TLS, so remove the CA config from the installed compose.
  $c = [IO.File]::ReadAllText("$live\docker-compose.yml")
  $c = ($c -replace '(?m)^\s*NODE_EXTRA_CA_CERTS:.*\r?\n', '') -replace '(?m)^\s*- \./certs:/certs:ro\r?\n', ''
  [IO.File]::WriteAllText("$live\docker-compose.yml", $c)
  'no CA in the bundle -> CA config stripped from C:\n8n\docker-compose.yml.'
  '  Only if your network intercepts TLS (corporate proxy) AND n8n then logs "SSL Issue":'
  '  export YOUR network''s root CA to C:\n8n\certs\gateway-ca.pem and restore the two compose lines.'
}
foreach ($f in Get-ChildItem -LiteralPath "$proj\scripts" -File) {
  Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $live $f.Name) -Force
}
"installed runtime files to $live"

docker volume inspect n8n_data 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { docker volume create n8n_data | Out-Null; 'created volume n8n_data (fresh instance - empty)' } else { 'volume n8n_data already exists (your workflows/credentials/encryption key are in there)' }

docker compose -f "$live\docker-compose.yml" up -d
"waiting for n8n ..."
Start-Sleep -Seconds 12
powershell -ExecutionPolicy Bypass -File "$live\status.ps1"

@"

Next, by hand (secrets are deliberately not in this bundle):
  1. http://localhost:5678 - create the owner account on first start.
  2. Settings -> n8n API keys -> create one, save it to `$env:USERPROFILE\.config\opencode\n8n-key`.
  3. Credentials: Confluence Basic Auth (your account + API token) and 'Ollama (local)'
     baseUrl http://host.docker.internal:11434 (only needed if you install Ollama).
   4. Import backups\workflows\*.json, open 'Cert List expiry reminder (Teams)':
      - 'Fetch Cert List Page': replace the YOUR-TENANT / PAGE_ID placeholders with your own Confluence page.
      - 'Send Teams 1 - Incoming Webhook': paste your Power Automate HTTP-trigger URL (the ?sig=... one).
   5. C:\n8n\parse-build.js top knobs: EMAIL_TO and PAGE_URL are placeholders - set them to yours,
      then push with: node C:\n8n\set-code.mjs
   6. Dry test: node C:\n8n\clone-webhook.mjs create -> run <id> -> delete <id>
"@
