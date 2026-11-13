# Tell flow manual proof

ENGINE-PLAN E13 asks for a manual proof against the sponsor's Power Automate flow. It needs a person with access to the flow, Teams and the mailbox, so no test runs it. Run it once before the Tell flow is turned on in Azure, and keep what it shows in this folder.

Never save the flow's address here. Its `sig=` part is the key. Crop it out of every screenshot.

## What the platform sends

The platform sends one `POST` with a JSON body, in the shape the team's cert reminder flow already takes. `sample-body.json` is a real body, made by `platform_api.orchestration.tell.compose`.

| Field | What it holds | Present when |
|---|---|---|
| `type` | Always `message`. | Always. |
| `attachments` | One Adaptive Card at `attachments[0].content`, with an `Open in AI Workflow Builder` button that opens the run. Empty when the block only emails. | The Tell block posts in Teams. |
| `emailSubject` | The email's subject. | The Tell block emails. |
| `emailHtml` | The email's body, in HTML, with one link back to the run. | The Tell block emails. |
| `emailTo` | The team's list from `TELL_EMAIL_TO`, separated by `;`. | The Tell block emails. |

The platform sends once. It does not send again after a `5xx` or a timeout, so the flow must answer within 10 seconds. The default answer, `202 Accepted`, is right.

## 1. Set up the flow

In Power Automate, in the account that may post in the team's channel:

1. Trigger **When an HTTP request is received**, method `POST`, with this request body schema:

   ```json
   {
     "type": "object",
     "properties": {
       "type": { "type": "string" },
       "attachments": { "type": "array" },
       "emailSubject": { "type": "string" },
       "emailHtml": { "type": "string" },
       "emailTo": { "type": "string" }
     }
   }
   ```

2. Add a **Condition** that `length(triggerBody()?['attachments'])` is greater than `0`. On **True**, add **Post card in a chat or channel**, posted as the Flow bot, in the channel that `TEAMS_CHANNEL` names, with the card `first(triggerBody()?['attachments'])?['content']`.
3. Add a second **Condition** that `empty(triggerBody()?['emailHtml'])` is `false`. On **True**, add **Send an email (V2)** with To `triggerBody()?['emailTo']`, Subject `triggerBody()?['emailSubject']` and Body `triggerBody()?['emailHtml']`. Type each of these in the **Expression** tab, or it arrives as literal text.
4. Save, and copy the trigger's address.

The email list lives in the platform, not in the flow. Leave **To** as the expression above. Do not type addresses into it.

## 2. Prove the flow takes our body

1. Copy `sample-body.json` to a scratch file and change `emailTo` to your own address.
2. Post it, with the address in a shell variable so it stays out of your history:

   ```sh
   read -r -s TELL_FLOW && curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
     -H 'Content-Type: application/json' --data @body.json "$TELL_FLOW"
   ```

3. Check each of these, and tick it here with the date:
   - [ ] curl prints `202`.
   - [ ] The card shows in the channel, with both blocks and their lines, and the `Open in AI Workflow Builder` button.
   - [ ] The email arrives at your address, with the subject `Cert list expiry reminder: what this run found` and the `Open the run in AI Workflow Builder` link.
   - [ ] Nothing in the card or the email is a link except that one.
4. Post the same body with `"attachments": []`. Only the email arrives.
5. Post it without the three `email` fields. Only the card arrives.
6. Save screenshots of the card and the email as `card.png` and `email.png`, and the flow's run history as `flow-runs.png`.

## 3. Turn it on

These change cloud settings, so the team lead does them.

1. In the GitHub repository, add the secret `TEAMS_TELL_WEBHOOK_URL` with the flow's address, and the secret `TELL_EMAIL_TO` with the team's list, separated by commas.
2. Check that the repository variable `TEAMS_CHANNEL` names the channel the flow posts in.
3. Run the deploy. Terraform keeps the address in Key Vault as `teams-tell-webhook-url`.
4. In the Portal, check:
   - [ ] **Settings, Connections** shows **Tell flow** as **Set**, with the channel and the list, and not the address.
   - [ ] **What can you do?** in the chat lists **Posts in Teams and emails**, and the Not yet note no longer names Teams channels or email.
5. Once a workflow can hold a Tell block (E14, the cert reminder), check:
   - [ ] A test run of a workflow with a Tell block says `Would have posted to … and emailed the team's list. Nothing was sent in a test run.`, and nothing arrives.
   - [ ] A real run's activity says `Posted to … and emailed the team's list.`, and the card and email arrive once.

## 4. Record

Add a dated line under this heading with who ran it, which flow (by name, never by address), and the screenshots' file names.
