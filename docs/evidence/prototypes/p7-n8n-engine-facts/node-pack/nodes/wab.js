const crypto = require('crypto');
const fs = require('fs');
const { NodeOperationError } = require('n8n-workflow');

const START_NODE = 'Start from the Portal';

function hmac(secret, text) {
  return crypto.createHmac('sha256', secret).update(text).digest('hex');
}

function sameHex(a, b) {
  const x = Buffer.from(String(a || ''), 'hex');
  const y = Buffer.from(String(b || ''), 'hex');
  return x.length === y.length && x.length > 0 && crypto.timingSafeEqual(x, y);
}

function guardOff() {
  return process.env.P7_GUARD_OFF === '1';
}

function startItem(ctx) {
  try {
    return ctx.evaluateExpression(`{{ $('${START_NODE}').first().json }}`, 0) || null;
  } catch (error) {
    return { unreadable: error.message };
  }
}

async function callApi(ctx, path, body) {
  const base = process.env.WAB_API_URL;
  const key = process.env.WAB_NODE_KEY;
  if (!base || !key) throw new NodeOperationError(ctx.getNode(), 'WAB_API_URL or WAB_NODE_KEY is not set');
  const flag = `/tmp/p7-fail-${ctx.getNode().name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  if (fs.existsSync(flag)) throw new NodeOperationError(ctx.getNode(), `Failed before calling our API (${flag})`);
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-wab-node-key': key },
    body: JSON.stringify({
      execution_id: ctx.getExecutionId(),
      workflow_id: ctx.getWorkflow().id,
      node_name: ctx.getNode().name,
      mode: ctx.getMode(),
      start_item: startItem(ctx),
      ...body,
    }),
  });
  const answer = await res.json().catch(() => ({}));
  if (res.status >= 500) throw new Error(`Our API answered ${res.status}`);
  if (res.status >= 400) throw new NodeOperationError(ctx.getNode(), answer.detail || `Our API answered ${res.status}`);
  return answer;
}

module.exports = { START_NODE, hmac, sameHex, guardOff, callApi };
