// Load a .js file into a workflow's Code node, so each script lives in a reviewable file.
//   node C:\n8n\set-code.mjs [file] [workflowId] [nodeName]
// Defaults: C:\n8n\parse-build.js, the cert reminder workflow, its parser node.
// (PowerShell 5.1 stalls on ConvertTo-Json with a large jsCode string, hence Node for this job.)
import fs from 'node:fs';

const [file = 'C:\\n8n\\parse-build.js', wfId = 'PI5CBumIHtf59dIm', nodeName = 'Parse Validity End & Build Reminder'] = process.argv.slice(2);
const base = 'http://localhost:5678/api/v1';
const key = fs.readFileSync(`${process.env.USERPROFILE}\\.config\\opencode\\n8n-key`, 'utf8').trim();
const headers = { 'X-N8N-API-KEY': key };

const code = fs.readFileSync(file, 'utf8');
const wf = await (await fetch(`${base}/workflows/${wfId}`, { headers })).json();
const node = wf.nodes.find((n) => n.name === nodeName);
if (!node) throw new Error(`node "${nodeName}" not found in ${wfId} (has: ${wf.nodes.map((n) => n.name).join(', ')})`);
if (node.type !== 'n8n-nodes-base.code') throw new Error(`"${nodeName}" is a ${node.type}, not a Code node`);

node.parameters ||= {};
node.parameters.jsCode = code;
const res = await fetch(`${base}/workflows/${wfId}`, {
  method: 'PUT',
  headers: { ...headers, 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: wf.name, nodes: wf.nodes, connections: wf.connections, settings: wf.settings }),
});
if (!res.ok) {
  console.error(`PUT failed: HTTP ${res.status} ${(await res.text()).slice(0, 400)}`);
  process.exit(1);
}
const back = await (await fetch(`${base}/workflows/${wfId}`, { headers })).json();
const stored = back.nodes.find((n) => n.name === nodeName).parameters.jsCode;
console.log(stored === code
  ? `loaded ${file} -> "${nodeName}" (${code.length} chars), stored copy matches`
  : `WARNING stored jsCode differs (${stored?.length ?? 'none'} vs ${code.length} chars)`);
