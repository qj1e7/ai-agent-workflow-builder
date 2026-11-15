# Re-export every workflow + credential metadata (no secrets) to C:\n8n\backups.
# Run:  powershell -ExecutionPolicy Bypass -File C:\n8n\backup.ps1
$ErrorActionPreference = 'Stop'
$base = 'http://localhost:5678/api/v1'
$key = (Get-Content -LiteralPath "$env:USERPROFILE\.config\opencode\n8n-key" -Raw).Trim()
$H = @{ "X-N8N-API-KEY" = $key }
$dir = 'C:\n8n\backups'
$wfDir = Join-Path $dir 'workflows'
New-Item -ItemType Directory -Force -Path $wfDir | Out-Null

$health = try { (Invoke-WebRequest 'http://localhost:5678/healthz' -UseBasicParsing -TimeoutSec 5).Content } catch { 'DOWN' }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

$list = (Invoke-RestMethod -Uri "$base/workflows" -Headers $H).data
$names = @()
foreach ($w in $list) {
    $full = Invoke-RestMethod -Uri "$base/workflows/$($w.id)" -Headers $H
    $safe = ($full.name -replace '[^\w.-]', '_')
    $file = "$($w.id)__${safe}.json"
    # Power Automate webhook URLs carry a signature in ?sig= - treat them as secrets in backups.
    ($full | ConvertTo-Json -Depth 60) -replace 'sig=[A-Za-z0-9._~\-]+', 'sig=REDACTED' |
        Set-Content -LiteralPath (Join-Path $wfDir $file) -Encoding UTF8
    $names += "$($w.id) ($($w.name)) active=$($w.active) -> workflows\$file"
    "saved workflows\$file"
}

# remove exports of workflows that no longer exist
Get-ChildItem $wfDir -Filter '*.json' | ForEach-Object {
    $id = ($_.Name -split '__')[0]
    if ($list.id -notcontains $id) { Remove-Item $_.FullName -Force; "removed stale $($_.Name)" }
}

$creds = (Invoke-RestMethod -Uri "$base/credentials" -Headers $H).data |
    Select-Object id, name, type, createdAt, updatedAt
$creds | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $dir 'credentials-metadata.json') -Encoding UTF8

@(
    "backed up: $stamp"
    "healthz: $health"
    "image: $(docker inspect --format '{{.Config.Image}}' n8n 2>$null)"
    "n8n version: $(docker exec n8n n8n --version 2>$null)"
    "workflows: $($names -join ', ')"
    "credentials: $($creds.Count) (metadata only, no secrets)"
    'NOTE: workflow files reference credential IDs but never contain secrets.'
    'NOTE: secrets are encrypted inside the n8n_data docker volume; the encryption key lives in that volume too.'
    'NOTE: a workflow export is useless without the n8n_data volume or re-created credentials.'
) | Set-Content -LiteralPath (Join-Path $dir 'MANIFEST.txt') -Encoding UTF8

"wrote MANIFEST.txt ($($names.Count) workflows, $($creds.Count) credentials)"
