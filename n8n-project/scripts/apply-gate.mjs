// Repair / verify the optional-AI part of the cert reminder workflow.
//   node C:\n8n\apply-gate.mjs [workflowId]
// Why this file exists: an open n8n browser tab keeps its own draft and autosaves it, which has twice
// silently overwrote API-made edits (dropped the gate nodes on 2026-11-09; dropped the model->chain link,
// the model name and the parser's JSON schema on 2026-11-10). Close the workflow tab before editing via
// the API, then run this - it is idempotent and prints what it restored.
import fs from 'node:fs';

const wfId = process.argv[2] || 'PI5CBumIHtf59dIm';
const base = 'http://localhost:5678/api/v1';
const key = fs.readFileSync(`${process.env.USERPROFILE}\\.config\\opencode\\n8n-key`, 'utf8').trim();
const H = { 'X-N8N-API-KEY': key };
const uuid = () => crypto.randomUUID();

const CHAIN = 'Interpret Rows (Ollama)';
const MODEL = 'Ollama Chat Model';
const PARSER = 'Structured Notes';
const PROBE = 'Ollama Reachable?';
const GATE = 'Local Model Available?';
const PARSE = 'Parse Validity End & Build Reminder';
const MERGE = 'Merge AI Notes';
const MERGE_FILE = 'C:\\n8n\\merge-ai.js';

const SYSTEM_PROMPT = 'You triage an internal TLS certificate inventory. Each row is a certificate whose VALIDITY END cell could not be trusted automatically. Buckets: no-environment = the ENV column is empty; unreadable-date = the cell has no parseable date; expired-long-ago = a date more than 12 months in the past; duplicate-row = the same row appears twice on the page. For EVERY row given return an entry with: id (copy it exactly), interpretation (what the cell most likely means, max 90 chars), probableDate (yyyy-mm-dd only if the cell text supports it, otherwise an empty string), confidence (low, medium or high), action (one short imperative instruction for the owner, max 80 chars). Never invent a date the text does not support - prefer an empty probableDate with low confidence. Answer with JSON only.';

const JSON_EXAMPLE = '{\n  "notes": [\n    { "id": "n1", "interpretation": "Renewed 14 May 2026, annual cycle", "probableDate": "2027-05-14", "confidence": "low", "action": "Confirm the date and fill ENV" }\n  ]\n}';

const wf = await (await fetch(`${base}/workflows/${wfId}`, { headers: H })).json();
const byName = new Map(wf.nodes.map((n) => [n.name, n]));
const fixed = [];

const wantNode = (spec) => {
  const cur = byName.get(spec.name);
  if (!cur) {
    wf.nodes.push({ ...spec });
    fixed.push(`added node ${spec.name}`);
    byName.set(spec.name, wf.nodes.find((n) => n.name === spec.name));
    return;
  }
  if (cur.type !== spec.type) {
    cur.type = spec.type;
    fixed.push(`${spec.name}: type -> ${spec.type}`);
  }
};

const setParams = (name, patch, label = '') => {
  const node = byName.get(name);
  if (!node) return;
  node.parameters ||= {};
  const before = JSON.stringify(node.parameters);
  for (const [k, v] of Object.entries(patch)) {
    if (JSON.stringify(node.parameters[k]) !== JSON.stringify(v)) {
      node.parameters[k] = v;
      fixed.push(`${name}: ${label || k}`);
    }
  }
  if (JSON.stringify(node.parameters) !== before && !fixed.some((f) => f.startsWith(`${name}:`))) fixed.push(`${name}: parameters`);
};

const link = (from, to, type, index = 0) => {
  const c = (wf.connections[from] ||= {});
  const groups = (c[type] ||= []);
  const arr = (groups[index] ||= []);
  const existing = arr.find((x) => x.node === to);
  if (!existing) {
    // The entry's own `type` must equal the group key - n8n's activation check reads it, and a
    // "main" entry inside an ai_languageModel group means "Model input not connected".
    arr.push({ node: to, type, index: 0 });
    fixed.push(`link ${from} [${type}:${index}] -> ${to}`);
  } else if (existing.type !== type) {
    existing.type = type;
    fixed.push(`fix entry type ${from} [${type}:${index}] -> ${to}`);
  }
};

const unlink = (from, to, type, index = 0) => {
  const arr = wf.connections[from]?.[type]?.[index];
  if (arr?.some((x) => x.node === to)) {
    wf.connections[from][type][index] = arr.filter((x) => x.node !== to);
    fixed.push(`unlink ${from} [${type}:${index}] -> ${to}`);
  }
};

// nodes
wantNode({
  id: uuid(), name: PROBE, type: 'n8n-nodes-base.httpRequest', typeVersion: 4.2, position: [-1344, 240],
  onError: 'continueErrorOutput',
  notes: 'Cheap probe so a laptop without Ollama skips the AI step instead of erroring on every run. Error output goes to the same IF, where the condition is simply false.',
  parameters: { method: 'GET', url: 'http://host.docker.internal:11434/api/tags', options: { timeout: 4000 } },
});
wantNode({
  id: uuid(), name: GATE, type: 'n8n-nodes-base.if', typeVersion: 2.2, position: [-1152, 240],
  parameters: {
    conditions: {
      combinator: 'and',
      conditions: [
        { leftValue: '={{ ($json.models ?? []).length }}', rightValue: 0, operator: { type: 'number', operation: 'gt' } },
        { leftValue: `={{ ($('${PARSE}').first().json.needsRows ?? []).length }}`, rightValue: 0, operator: { type: 'number', operation: 'gt' } },
      ],
      options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
    },
    options: {},
  },
});

setParams(MODEL, { model: 'llama3.1:8b', options: { temperature: 0 } });
setParams(PARSER, { schemaType: 'fromJson', jsonExample: JSON_EXAMPLE, autoFix: true });
setParams(CHAIN, {
  promptType: 'define',
  text: `=Rows to interpret (JSON array):\n{{ JSON.stringify($json.needsRows) }}`,
  hasOutputParser: true,
  messages: { messageValues: [{ type: 'SystemMessagePromptTemplate', messageType: 'text', message: SYSTEM_PROMPT }] },
});
if (byName.get(CHAIN) && byName.get(CHAIN).onError !== 'continueErrorOutput') {
  byName.get(CHAIN).onError = 'continueErrorOutput';
  fixed.push(`${CHAIN}: onError=continueErrorOutput`);
}
if (!byName.get(MODEL)?.credentials?.ollamaApi) {
  fixed.push(`${MODEL}: no ollamaApi credential attached - attach "Ollama (local)" in the UI`);
}

// connections
unlink(PARSE, CHAIN);
unlink(CHAIN, MERGE, 'main', 1);
link(PARSE, PROBE, 'main', 0);
link(PROBE, GATE, 'main', 0);
link(PROBE, GATE, 'main', 1);
link(GATE, CHAIN, 'main', 0);
link(GATE, MERGE, 'main', 1);
link(CHAIN, MERGE, 'main', 0);
link(CHAIN, MERGE, 'main', 1);
link(MODEL, CHAIN, 'ai_languageModel', 0);
link(MODEL, PARSER, 'ai_languageModel', 0);
link(PARSER, CHAIN, 'ai_outputParser', 0);

// duplicate links (a second apply used to add these)
for (const conns of Object.values(wf.connections)) {
  for (const [type, groups] of Object.entries(conns)) {
    groups.forEach((g, i) => {
      if (!g) return;
      const seen = new Set();
      groups[i] = g.filter((x) => {
        const k = `${x.node}|${x.index ?? 0}`;
        if (seen.has(k)) { fixed.push(`removed duplicate ${type}:${i} link`); return false; }
        seen.add(k);
        return true;
      });
    });
  }
}

if (!fixed.length) console.log('AI step already correct - nothing to change');
else {
  const res = await fetch(`${base}/workflows/${wfId}`, {
    method: 'PUT',
    headers: { ...H, 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: wf.name, nodes: wf.nodes, connections: wf.connections, settings: wf.settings }),
  });
  if (!res.ok) {
    console.error(`PUT failed: HTTP ${res.status} ${(await res.text()).slice(0, 400)}`);
    process.exit(1);
  }
  console.log(`repaired ${fixed.length} thing(s):`);
  fixed.forEach((f) => console.log('  - ' + f));
}

const back = await (await fetch(`${base}/workflows/${wfId}`, { headers: H })).json();
const names = new Set(back.nodes.map((n) => n.name));
const has = (from, to, type = 'main', index = 0) => (back.connections[from]?.[type]?.[index] || []).some((x) => x.node === to);
const code = byName.get(MERGE) ? fs.readFileSync(MERGE_FILE, 'utf8') : '';
const storedMerge = back.nodes.find((n) => n.name === MERGE)?.parameters?.jsCode ?? '';
console.log(`verify: nodes=${back.nodes.length} active=${back.active}`);
console.log(`  ${PROBE} present=${names.has(PROBE)}  ${GATE} present=${names.has(GATE)}`);
console.log(`  ${MODEL} model=${JSON.stringify(back.nodes.find((n) => n.name === MODEL)?.parameters?.model ?? null)}`);
console.log(`  ${PARSER} schemaType=${JSON.stringify(back.nodes.find((n) => n.name === PARSER)?.parameters?.schemaType ?? null)} jsonExample=${back.nodes.find((n) => n.name === PARSER)?.parameters?.jsonExample ? 'set' : 'MISSING'}`);
console.log(`  links: parse->probe=${has(PARSE, PROBE)} probe->gate=${has(PROBE, GATE)} gate->chain=${has(GATE, CHAIN)} gate->merge(false)=${has(GATE, MERGE, 'main', 1)} model->chain=${has(MODEL, CHAIN, 'ai_languageModel')} model->parser=${has(MODEL, PARSER, 'ai_languageModel')} parser->chain=${has(PARSER, CHAIN, 'ai_outputParser')}`);
if (storedMerge && storedMerge !== code) console.log(`  NOTE ${MERGE} jsCode differs from ${MERGE_FILE} -> node C:\\n8n\\set-code.mjs ${MERGE_FILE} ${wfId} "${MERGE}"`);
