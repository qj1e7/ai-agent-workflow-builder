param([Parameter(Mandatory = $true)][string]$Action, [string]$Id, [string]$Url, [string]$Path = 'cert-list-dryrun')

$ErrorActionPreference = 'Stop'
$base = 'http://localhost:5678/api/v1'
$REAL = 'PI5CBumIHtf59dIm'
$key = (Get-Content -LiteralPath "$env:USERPROFILE\.config\opencode\n8n-key" -Raw).Trim()
$H = @{ "X-N8N-API-KEY" = $key }

function NewId { return [guid]::NewGuid().ToString() }

switch ($Action) {
    'create' {
        $wf = Invoke-RestMethod -Uri "$base/workflows/$REAL" -Headers $H
        $byName = @{}
        foreach ($n in $wf.nodes) { $byName[$n.name] = $n }

        $fetch = $byName['Fetch Cert List Page']
        $fetch.id = NewId
        if ($fetch.PSObject.Properties['webhookId']) { $fetch.PSObject.Properties.Remove('webhookId') }
        $fetch.retryOnFail = $false
        $fetch.onError = 'continueErrorOutput'
        $fetch.notes = 'TMP test copy - do not edit the real workflow copy'

        $code = $byName['Parse Validity End & Build Reminder']
        $code.id = NewId
        $code.onError = 'continueErrorOutput'

        $notice = $byName['Build Failure Notice']
        $notice.id = NewId

        $webhook = [pscustomobject]@{
            id = NewId; name = 'Trigger (test)'; type = 'n8n-nodes-base.webhook'; typeVersion = 2
            position = @(-1500, 112)
            parameters = @{ httpMethod = 'POST'; path = $Path; responseMode = 'responseNode'; options = @{} }
        }
        $ok = [pscustomobject]@{
            id = NewId; name = 'Respond Success'; type = 'n8n-nodes-base.respondToWebhook'; typeVersion = 1.4
            position = @(-736, 112)
            parameters = @{
                respondWith = 'json'
                responseBody = '={{ JSON.stringify({ hasAlerts: $json.hasAlerts, subject: $json.subject, rowsRead: $json.rowsRead, attentionCount: $json.attentionCount, expiredCount: $json.expiredCount, expiringCount: $json.expiringCount, staleCount: $json.staleCount, duplicateCount: $json.duplicateCount, unreadableCount: $json.unreadableCount, cardType: JSON.parse($json.teamsWebhookPayload).type, textPreview: $json.teamsText.slice(0, 1800) }) }}'
                options = @{ responseCode = 200 }
            }
        }
        $bad = [pscustomobject]@{
            id = NewId; name = 'Respond Failure'; type = 'n8n-nodes-base.respondToWebhook'; typeVersion = 1.4
            position = @(-464, 512)
            parameters = @{
                respondWith = 'json'
                responseBody = '={{ JSON.stringify({ failure: true, errorStage: $json.errorStage, errorMessage: $json.errorMessage, cardType: JSON.parse($json.teamsWebhookPayload).type, textPreview: $json.teamsText.slice(0, 900) }) }}'
                options = @{ responseCode = 502 }
            }
        }

        $conns = [ordered]@{
            'Trigger (test)'                      = @{ main = , @(@(@{ node = 'Fetch Cert List Page'; type = 'main'; index = 0 })) }
            'Fetch Cert List Page'                = @{ main = @(@(@{ node = 'Parse Validity End & Build Reminder'; type = 'main'; index = 0 }), @(@{ node = 'Build Failure Notice'; type = 'main'; index = 0 })) }
            'Parse Validity End & Build Reminder' = @{ main = @(@(@{ node = 'Respond Success'; type = 'main'; index = 0 }), @(@{ node = 'Build Failure Notice'; type = 'main'; index = 0 })) }
            'Build Failure Notice'                = @{ main = , @(@(@{ node = 'Respond Failure'; type = 'main'; index = 0 })) }
        }

        $body = @{
            name        = 'TMP cert-list dry run (delete me)'
            nodes       = @($webhook, $fetch, $code, $notice, $ok, $bad)
            connections = $conns
            settings    = @{ executionOrder = 'v1' }
        } | ConvertTo-Json -Depth 40

        $created = Invoke-RestMethod -Uri "$base/workflows" -Method Post -Headers $H -ContentType 'application/json' -Body $body
        "CREATED $($created.id)"
    }

    'live' {
        # Same clone, but the real Teams sender stays in: this one actually posts to the channel.
        $wf = Invoke-RestMethod -Uri "$base/workflows/$REAL" -Headers $H
        $byName = @{}
        foreach ($n in $wf.nodes) { $byName[$n.name] = $n }

        $fetch = $byName['Fetch Cert List Page']
        $fetch.id = NewId
        if ($fetch.PSObject.Properties['webhookId']) { $fetch.PSObject.Properties.Remove('webhookId') }
        $fetch.retryOnFail = $false
        $fetch.notes = 'TMP live test copy'

        $code = $byName['Parse Validity End & Build Reminder']
        $code.id = NewId

        $notice = $byName['Build Failure Notice']
        $notice.id = NewId

        $send = $byName['Send Teams 1 - Incoming Webhook']
        $send.id = NewId
        if ($send.PSObject.Properties['webhookId']) { $send.PSObject.Properties.Remove('webhookId') }
        $send.retryOnFail = $false
        $send.notes = 'TMP live test copy - posts for real into the Teams channel'

        $webhook = [pscustomobject]@{
            id = NewId; name = 'Trigger (live)'; type = 'n8n-nodes-base.webhook'; typeVersion = 2
            position = @(-1500, 112)
            parameters = @{ httpMethod = 'POST'; path = $Path; responseMode = 'responseNode'; options = @{} }
        }
        $done = [pscustomobject]@{
            id = NewId; name = 'Respond Done'; type = 'n8n-nodes-base.respondToWebhook'; typeVersion = 1.4
            position = @(-160, 112)
            parameters = @{
                respondWith = 'json'
                responseBody = '={{ JSON.stringify({ finished: true, delivered: $json.statusCode, note: "check the cert-expiry-reminder channel", at: $now.toISO() }) }}'
                options = @{ responseCode = 200 }
            }
        }

        $conns = [ordered]@{
            'Trigger (live)'                      = @{ main = , @(@(@{ node = 'Fetch Cert List Page'; type = 'main'; index = 0 })) }
            'Fetch Cert List Page'                = @{ main = @(@(@{ node = 'Parse Validity End & Build Reminder'; type = 'main'; index = 0 }), @(@{ node = 'Build Failure Notice'; type = 'main'; index = 0 })) }
            'Parse Validity End & Build Reminder' = @{ main = @(@(@{ node = 'Send Teams 1 - Incoming Webhook'; type = 'main'; index = 0 }), @(@{ node = 'Build Failure Notice'; type = 'main'; index = 0 })) }
            'Build Failure Notice'                = @{ main = , @(@(@{ node = 'Send Teams 1 - Incoming Webhook'; type = 'main'; index = 0 })) }
            'Send Teams 1 - Incoming Webhook'     = @{ main = , @(@(@{ node = 'Respond Done'; type = 'main'; index = 0 })) }
        }

        $body = @{
            name        = 'TMP cert-list LIVE test (delete me)'
            nodes       = @($webhook, $fetch, $code, $notice, $send, $done)
            connections = $conns
            settings    = @{ executionOrder = 'v1' }
        } | ConvertTo-Json -Depth 40

        $created = Invoke-RestMethod -Uri "$base/workflows" -Method Post -Headers $H -ContentType 'application/json' -Body $body
        "CREATED $($created.id)"
    }

    'iftest' {
        $flag = ($Url -eq 'true')
        $wf = Invoke-RestMethod -Uri "$base/workflows/$REAL" -Headers $H
        $byName = @{}
        foreach ($n in $wf.nodes) { $byName[$n.name] = $n }
        $if = $byName['Anything to report?']; $if.id = NewId
        $ac = $byName['All Clear (nothing sent)']; $ac.id = NewId

        $webhook = [pscustomobject]@{ id = NewId; name = 'Trigger (if)'; type = 'n8n-nodes-base.webhook'; typeVersion = 2; position = @(-1500, 112); parameters = @{ httpMethod = 'POST'; path = $Path; responseMode = 'responseNode'; options = @{} } }
        $fake = [pscustomobject]@{
            id = NewId; name = 'Fake Report'; type = 'n8n-nodes-base.set'; typeVersion = 3.4; position = @(-1264, 112)
            parameters = @{ assignments = @{ assignments = @(
                    @{ id = 'f1'; name = 'hasAlerts'; type = 'boolean'; value = $flag },
                    @{ id = 'f2'; name = 'subject'; type = 'string'; value = 'FAKE subject for branch test' },
                    @{ id = 'f3'; name = 'checkedAt'; type = 'string'; value = '={{ $now.toISO() }}' },
                    @{ id = 'f4'; name = 'rowsRead'; type = 'number'; value = 46 }
                ) }; options = @{} }
        }
        $rt = [pscustomobject]@{
            id = NewId; name = 'Respond True'; type = 'n8n-nodes-base.respondToWebhook'; typeVersion = 1.4; position = @(-464, -64)
            parameters = @{ respondWith = 'json'; responseBody = '={{ JSON.stringify({ branch: "true", senderWouldBe: "Send Teams 1 - Incoming Webhook", subject: $json.subject }) }}'; options = @{ responseCode = 200 } }
        }
        $rf = [pscustomobject]@{
            id = NewId; name = 'Respond False'; type = 'n8n-nodes-base.respondToWebhook'; typeVersion = 1.4; position = @(-192, 400)
            parameters = @{ respondWith = 'json'; responseBody = '={{ JSON.stringify({ branch: "false", result: $json.result, checkedAt: $json.checkedAt, rowsRead: $json.rowsRead }) }}'; options = @{ responseCode = 200 } }
        }
        $conns = [ordered]@{
            'Trigger (if)'        = @{ main = , @(@(@{ node = 'Fake Report'; type = 'main'; index = 0 })) }
            'Fake Report'         = @{ main = , @(@(@{ node = 'Anything to report?'; type = 'main'; index = 0 })) }
            'Anything to report?' = @{ main = @(@(@{ node = 'Respond True'; type = 'main'; index = 0 }), @(@{ node = 'All Clear (nothing sent)'; type = 'main'; index = 0 })) }
            'All Clear (nothing sent)' = @{ main = , @(@(@{ node = 'Respond False'; type = 'main'; index = 0 })) }
        }
        $body = @{ name = 'TMP cert-list IF branch test (delete me)'; nodes = @($webhook, $fake, $if, $ac, $rt, $rf); connections = $conns; settings = @{ executionOrder = 'v1' } } | ConvertTo-Json -Depth 40
        $created = Invoke-RestMethod -Uri "$base/workflows" -Method Post -Headers $H -ContentType 'application/json' -Body $body
        "CREATED $($created.id)"
    }
    'seturl' {
        $wf = Invoke-RestMethod -Uri "$base/workflows/$Id" -Headers $H
        $f = $wf.nodes | Where-Object { $_.name -eq 'Fetch Cert List Page' }
        $f.parameters.url = $Url
        $body = @{ name = $wf.name; nodes = $wf.nodes; connections = $wf.connections; settings = $wf.settings } | ConvertTo-Json -Depth 40
        Invoke-RestMethod -Uri "$base/workflows/$Id" -Method Put -Headers $H -ContentType 'application/json' -Body $body | Out-Null
        "URL now: $Url"
    }

    'run' {
        Invoke-RestMethod -Uri "$base/workflows/$Id/activate" -Method Post -Headers $H -ContentType 'application/json' -Body '{}' | Out-Null
        Start-Sleep -Seconds 8
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:5678/webhook/$Path" -Method Post -Body '{}' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 90
            "HTTP $($r.StatusCode)"; $r.Content
        } catch {
            $resp = $_.Exception.Response
            if ($resp) {
                $sr = New-Object IO.StreamReader($resp.GetResponseStream())
                "HTTP $([int]$resp.StatusCode)"; $sr.ReadToEnd()
            } else { "NO RESPONSE: $($_.Exception.Message)" }
        }
    }

    'delete' {
        Invoke-RestMethod -Uri "$base/workflows/$Id/deactivate" -Method Post -Headers $H -ContentType 'application/json' -Body '{}' | Out-Null
        Invoke-RestMethod -Uri "$base/workflows/$Id" -Method Delete -Headers $H | Out-Null
        "DELETED $Id"
    }
}
