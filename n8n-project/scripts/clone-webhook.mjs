// Clone the cert reminder workflow into a throwaway webhook workflow, so a manual-trigger-only
// workflow can be run (and its delivery tested) over HTTP.
//
//   node C:\n8n\clone-webhook.mjs create            dry run: senders removed, ends in a Respond node
//   node C:\n8n\clone-webhook.mjs create --send     live test: keeps Send Teams 1, really posts
//   node C:\n8n\clone-webhook.mjs run <id>          activate + POST + report, prints the last execution id
//   node C:\n8n\clone-webhook.mjs delete <id>       deactivate + delete
//
// Every node of the real workflow is copied (AI sub-nodes included), so the clone stays honest as the
// workflow evolves. Delete the clone afterwards: an active clone is an open webhook.
import crypto from 'node:crypto';

const REAL = 'PI5CBumIHtf59dIm';
const DROP_ALWAYS = ['Manual Trigger', 'Sticky Note'];
const args = process.argv.slice(2);
const action = args[0];
const idArg = args[1];
const send = args.includes('--send');
const pathIdx = args.indexOf('--path');
const path = pathIdx >= 0 ? args[pathIdx + 1] : 'cert-list-clone';

const base = 'http://localhost:5678/api/v1';
const key = (await import('node:fs')).default.readFileSync(`${process.env.USERPROFILE}\\.config\\opencode\\n8n-key`, 'utf8').trim();
const H = { 'X-N8N-API-KEY': key };
const json = (init = {}) => ({ ...init, headers: { ...H, ...(init.headers || {}) } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (action === 'create') {
  const wf = await (await fetch(`${base}/workflows/${REAL}`, json())).json();
  const senderName = 'Send Teams 1 - Incoming Webhook';
  const drop = new Set([...DROP_ALWAYS, 'Send Email Alert', ...(send ? [] : [senderName])]);
  const nodes = wf.nodes.filter((n) => !drop.has(n.name)).map((n) => ({ ...structuredClone(n), id: crypto.randomUUID() }));
  const kept = new Set(nodes.map((n) => n.name));

  if (!send) {
    // Replace the real sender with a Set node of the SAME NAME: the branch structure stays exactly
    // as in production, and the Respond node always gets an answer instead of hanging.
    nodes.push({
      id: crypto.randomUUID(), name: senderName, type: 'n8n-nodes-base.set', typeVersion: 3.4, position: [-300, 112],
      parameters: {
        assignments: {
          assignments: [
            { id: 'd1', name: 'dryRun', type: 'boolean', value: true },
            { id: 'd2', name: 'subject', type: 'string', value: '={{ $json.subject }}' },
            { id: 'd3', name: 'cardChars', type: 'number', value: '={{ ($json.teamsWebhookPayload || "").length }}' },
            { id: 'd4', name: 'emailChars', type: 'number', value: '={{ ($json.emailHtml || "").length }}' },
            { id: 'd5', name: 'aiReason', type: 'string', value: '={{ $json.aiReason }}' },
          ],
        },
        options: {},
      },
    });
    kept.add(senderName);
  }

  const connections = {};
  for (const [source, conns] of Object.entries(wf.connections)) {
    if (!kept.has(source) || source === 'Manual Trigger') continue;
    const out = {};
    for (const [type, groups] of Object.entries(conns)) {
      // Keep the group INDEX even when it becomes empty: dropping an empty group silently
      // promotes the IF's false branch into the true branch slot (that fake "All Clear ran" bug).
      const g = (groups || []).map((group) => (group || []).filter((t) => kept.has(t.node)));
      if (g.some((group) => group.length)) out[type] = g;
    }
    if (Object.keys(out).length) connections[source] = out;
  }

  const target = (wf.connections['Manual Trigger']?.main?.[0] || []).map((t) => t.node).filter((n) => kept.has(n));
  const webhook = {
    id: crypto.randomUUID(), name: 'Trigger (clone)', type: 'n8n-nodes-base.webhook', typeVersion: 2,
    position: [-1600, 112],
    parameters: { httpMethod: 'POST', path, responseMode: 'responseNode', options: {} },
  };
  const respond = {
    id: crypto.randomUUID(), name: 'Respond Clone', type: 'n8n-nodes-base.respondToWebhook', typeVersion: 1.4,
    position: [400, 112],
    parameters: {
      respondWith: 'json',
      responseBody: '={{ JSON.stringify({ leaf: $json.leaf ?? null, senderOutput: JSON.stringify($json).slice(0, 300), subject: $("Merge AI Notes").first().json.subject, emailSubject: $("Merge AI Notes").first().json.emailSubject, aiCovered: $("Merge AI Notes").first().json.aiCovered, aiUsed: $("Merge AI Notes").first().json.aiUsed, aiReason: $("Merge AI Notes").first().json.aiReason, emailHtmlChars: $("Merge AI Notes").first().json.emailHtml.length, modelReadTableInEmail: $("Merge AI Notes").first().json.emailHtml.includes("Model read"), modelUnavailableNote: $("Merge AI Notes").first().json.emailHtml.includes("Local model unavailable"), confirmedCount: $("Merge AI Notes").first().json.confirmedCount }) }}',
      options: { responseCode: 200 },
    },
  };
  nodes.push(webhook, respond);

  if (target.length) connections['Trigger (clone)'] = { main: [target.map((node) => ({ node, type: 'main', index: 0 }))] };
  const hasMainOut = (name) => Boolean(connections[name]?.main?.some((g) => g?.length));
  const aiSubNodes = new Set(Object.entries(connections).filter(([, c]) => Object.keys(c).some((t) => t.startsWith('ai_'))).map(([src]) => src));
  const leaves = nodes.map((n) => n.name).filter((n) => !n.startsWith('Trigger (') && !n.startsWith('Respond ') && !aiSubNodes.has(n) && !hasMainOut(n));
  for (const leaf of leaves) {
    const c = (connections[leaf] ||= {});
    c.main = [...(c.main || []), [{ node: 'Respond Clone', type: 'main', index: 0 }]];
  }

  const created = await (await fetch(`${base}/workflows`, json({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: `TMP cert-list ${send ? 'LIVE' : 'dry'} clone (delete me)`,
      nodes,
      connections,
      settings: { executionOrder: 'v1' },
    }),
  }))).json();
  console.log(`CREATED ${created.id}  mode=${send ? 'live (posts to Teams)' : 'dry (no senders)'}  nodes=${nodes.length}  leaves=${leaves.join(', ') || '-'}`);
} else if (action === 'run') {
  if (!idArg) throw new Error('run needs a workflow id');
  const act = await fetch(`${base}/workflows/${idArg}/activate`, json({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  if (!act.ok) {
    console.log(`activate failed: HTTP ${act.status} ${(await act.text()).slice(0, 600)}`);
    process.exit(1);
  }
  await sleep(8000);
  try {
    const r = await fetch(`http://localhost:5678/webhook/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    console.log('HTTP', r.status, await r.text());
  } catch (e) {
    console.log('request failed:', e.message);
  }
  const ex = await (await fetch(`${base}/executions?limit=1&workflowId=${idArg}`, json())).json();
  if (ex.data?.[0]) console.log('execution', ex.data[0].id, ex.data[0].status);
} else if (action === 'delete') {
  if (!idArg) throw new Error('delete needs a workflow id');
  await fetch(`${base}/workflows/${idArg}/deactivate`, json({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  let res;
  for (let i = 0; i < 6; i++) {
    res = await fetch(`${base}/workflows/${idArg}`, json({ method: 'DELETE' }));
    if (res.ok || res.status !== 409) break;
    await sleep(3000); // n8n answers 409 while the workflow is still being unpublished
  }
  console.log(res.ok ? `DELETED ${idArg}` : `delete failed: HTTP ${res.status} ${(await res.text()).slice(0, 200)}`);
} else {
  console.log('usage: node clone-webhook.mjs create [--send] [--path p] | run <id> [--path p] | delete <id>');
}
