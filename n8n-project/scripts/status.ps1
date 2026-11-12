# Health check for the n8n stack used by the Cert List expiry reminder project.
# Run:  powershell -File C:\n8n\status.ps1
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "== container ==" -ForegroundColor Cyan
docker ps -a --filter name=n8n --format "{{.Names}} | {{.Status}} | {{.Ports}}"

$health = $null
for ($i = 1; $i -le 9; $i++) {
    try { $health = (Invoke-WebRequest "http://localhost:5678/healthz" -UseBasicParsing -TimeoutSec 5).Content; break }
    catch {
        # n8n needs ~40-60s to boot, so a cold start is not an outage yet.
        if ($i -eq 1) { Write-Host "  waiting for n8n to answer /healthz ..." -ForegroundColor DarkGray } else { Write-Host "  still waiting ($i/9) ..." -ForegroundColor DarkGray }
        Start-Sleep -Seconds 10
    }
}
if (-not $health) {
    Write-Host "healthz    : DOWN - start with:  docker compose -f C:\n8n\docker-compose.yml up -d" -ForegroundColor Yellow
    return
}
Write-Host ("healthz    : " + $health)

Write-Host "== TLS from inside the container ==" -ForegroundColor Cyan
docker exec n8n node -e "fetch('https://n8n.io').then(r=>console.log('TLS ok (HTTP ' + r.status + ')')).catch(e=>console.log('TLS FAIL: ' + e.message + '  -> if your network intercepts HTTPS, is C:\n8n\certs\gateway-ca.pem present?'))"

$keyFile = "$env:USERPROFILE\.config\opencode\n8n-key"
if (Test-Path $keyFile) {
    $key = (Get-Content $keyFile -Raw).Trim()
    # Right after a start, /healthz answers ~10s before the REST router mounts ("Cannot GET /api/v1/...").
    Write-Host "== workflows ==" -ForegroundColor Cyan
    $tries = 0
    $wfs = $null
    while ($tries -lt 8) {
        $tries++
        try { $wfs = (Invoke-RestMethod "http://localhost:5678/api/v1/workflows" -Headers @{ "X-N8N-API-KEY" = $key }).data; break }
        catch { if ($tries -eq 1) { Write-Host "  waiting for the n8n API ..." -ForegroundColor DarkGray } else { Write-Host "  still waiting ($tries/8) ..." -ForegroundColor DarkGray }; Start-Sleep -Seconds 10 }
    }
    if (-not $wfs) {
        Write-Host "  n8n API still not answering after $tries tries - check: docker compose -f C:\n8n\docker-compose.yml logs --tail 50" -ForegroundColor Yellow
    } else {
        $wfs | ForEach-Object { Write-Host ("  {0}  active={1}  {2}" -f $_.id, $_.active, $_.name) }
        Write-Host "== credentials ==" -ForegroundColor Cyan
        (Invoke-RestMethod "http://localhost:5678/api/v1/credentials" -Headers @{ "X-N8N-API-KEY" = $key }).data |
            ForEach-Object { Write-Host ("  {0,-16} {1}" -f $_.type, $_.name) }
    }
}

Write-Host "== Sunny config ==" -ForegroundColor Cyan
$mcp = (Get-Content "$env:USERPROFILE\.config\opencode\opencode.jsonc" -Raw | ConvertFrom-Json).mcp
$mcp.PSObject.Properties.Name | ForEach-Object { Write-Host ("  mcp '{0}'  enabled={1}  {2}" -f $_, $mcp.$_.enabled, ($mcp.$_.command -join ' ')) }
Write-Host ("  skills: " + (Get-ChildItem "$env:USERPROFILE\.agents\skills\n8nSkills" -Directory).Count + " under ~\.agents\skills\n8nSkills")
Write-Host ("  api key file: " + (Test-Path $keyFile) + "   CA pem: " + (Test-Path "C:\n8n\certs\gateway-ca.pem"))
