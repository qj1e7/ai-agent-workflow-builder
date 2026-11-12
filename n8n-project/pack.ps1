# Sync this bundle with the live install (C:\n8n + the handoff doc), redacting secrets on the way in.
#   powershell -ExecutionPolicy Bypass -File .\pack.ps1
# Run it after any change to a script, the compose file, the CA, or the workflow itself.
# README.md is authored in this folder and never overwritten.
$ErrorActionPreference = 'Stop'
$proj = $PSScriptRoot
$live = 'C:\n8n'

$pairs = [ordered]@{
  'docker-compose.yml'                  = 'docker-compose.yml'
  'parse-build.js'                      = 'scripts\parse-build.js'
  'merge-ai.js'                         = 'scripts\merge-ai.js'
  'parse-test.js'                       = 'scripts\parse-test.js'
  'set-code.mjs'                        = 'scripts\set-code.mjs'
  'clone-webhook.mjs'                   = 'scripts\clone-webhook.mjs'
  'apply-gate.mjs'                      = 'scripts\apply-gate.mjs'
  'show-run.mjs'                        = 'scripts\show-run.mjs'
  'cert-dryrun.ps1'                     = 'scripts\cert-dryrun.ps1'
  'status.ps1'                          = 'scripts\status.ps1'
  'backup.ps1'                          = 'scripts\backup.ps1'
  'backups\MANIFEST.txt'                = 'backups\MANIFEST.txt'
  'backups\credentials-metadata.json'   = 'backups\credentials-metadata.json'
}

foreach ($srcRel in $pairs.Keys) {
  $src = Join-Path $live $srcRel
  $dst = Join-Path $proj $pairs[$srcRel]
  if (-not (Test-Path -LiteralPath $src)) { Write-Warning "missing in live install: $src"; continue }
  New-Item -ItemType Directory -Force -Path (Split-Path -LiteralPath $dst) | Out-Null
  Copy-Item -LiteralPath $src -Destination $dst -Force
  "copied  $($pairs[$srcRel])"
}

foreach ($wf in Get-ChildItem -LiteralPath "$live\backups\workflows" -Filter *.json) {
  $dst = Join-Path $proj "backups\workflows\$($wf.Name)"
  New-Item -ItemType Directory -Force -Path (Split-Path -LiteralPath $dst) | Out-Null
  Copy-Item -LiteralPath $wf.FullName -Destination $dst -Force
  "copied  backups\workflows\$($wf.Name)"
}

# Belt and braces: replace secrets AND site-specific identifiers on the way into the bundle.
# The live install (C:\n8n) keeps the real values; only bundle copies are rewritten.
# Recipients: YOUR-TENANT / PAGE_ID / your-*.example.internal / EMAIL_TO are input-you placeholders.
$redact = [ordered]@{
  'sig=(?!REDACTED)[A-Za-z0-9\-_]{10,}' = 'sig=REDACTED'
  'sgtechstack\.atlassian\.net'         = 'YOUR-TENANT.atlassian.net'
  '300338706'                           = 'PAGE_ID'
  '\.marriage\.gov\.sg'                 = '.example-certs.internal'
}
foreach ($f in Get-ChildItem -LiteralPath $proj -Recurse -File | Where-Object { $_.Name -ne 'pack.ps1' -and $_.Extension -in '.json', '.txt', '.md', '.yml', '.js', '.mjs', '.ps1', '.pem' }) {
  $text = [IO.File]::ReadAllText($f.FullName)
  $orig = $text
  foreach ($k in $redact.Keys) { $text = ([regex]$k).Replace($text, $redact[$k]) }
  if ($text -ne $orig) {
    [IO.File]::WriteAllText($f.FullName, $text)
    "redacted site-specific data in $($f.FullName.Substring($proj.Length + 1))"
  }
  $jwt = ([regex]'eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{5,}\.[A-Za-z0-9\-_]{5,}').Matches($text).Count
  if ($jwt) { "WARNING: JWT-like token still present in $($f.FullName.Substring($proj.Length + 1)) - check manually" }
}

$total = (Get-ChildItem -LiteralPath $proj -Recurse -File | Measure-Object Length -Sum)
"bundle ready: $($total.Count) files, $([Math]::Round($total.Sum / 1kb)) KB in $proj"
"no secrets: api keys and n8n's encryption key are NOT part of this bundle by design"
