import { createHmac, randomUUID } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { START_PATH, StartFromPortal } from '../src/nodes/StartFromPortal.node';
import { START_SECRET, setEnv, webhookContext } from './fake';

const now = () => Math.floor(Date.now() / 1000);

// The start our API sends. The signature is the contract: HMAC-SHA256 with WAB_START_SECRET over
// the nonce, the kind and the expiry (Unix seconds), one per line, in the X-Wab-Signature header.
function signedStart(overrides: { nonce?: string; kind?: string; expires?: number; secret?: string } = {}) {
  const body = { nonce: overrides.nonce ?? randomUUID(), kind: overrides.kind ?? 'run_now', expires: overrides.expires ?? now() + 300 };
  const signature = createHmac('sha256', overrides.secret ?? START_SECRET)
    .update(`${body.nonce}\n${body.kind}\n${body.expires}`)
    .digest('hex');
  return { body, headers: { 'x-wab-signature': signature }, signature };
}

async function deliver(start: { body: unknown; headers: Record<string, string> }) {
  const { ctx, response } = webhookContext(start);
  const out = await new StartFromPortal().webhook.call(ctx);
  return { out, status: response.status };
}

beforeEach(() => setEnv({ WAB_START_SECRET: START_SECRET }));
afterEach(() => setEnv({ WAB_START_SECRET: undefined }));

describe('Start from the Portal', () => {
  it('is a trigger with one fixed path and no fields', () => {
    const { description } = new StartFromPortal();
    expect(description.group).toEqual(['trigger']);
    expect(description.webhooks).toEqual([
      { name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: START_PATH, isFullPath: false },
    ]);
    expect(description.properties).toEqual([]);
  });

  it.each(['run_now', 'test', 'retry'])('starts one execution for a signed %s start', async (kind) => {
    const start = signedStart({ kind });
    const { out, status } = await deliver(start);
    expect(status).toBeUndefined();
    expect(out.workflowData).toEqual([[{ json: { ...start.body, signature: start.signature } }]]);
  });

  it.each([
    ['no signature', () => ({ ...signedStart(), headers: {} })],
    ['a signature made with another secret', () => signedStart({ secret: 'not-our-secret' })],
    ['a body changed after signing', () => {
      const start = signedStart({ kind: 'test' });
      return { ...start, body: { ...start.body, kind: 'run_now' } };
    }],
    ['an expiry in the past', () => signedStart({ expires: now() - 1 })],
    ['an expiry more than five minutes away', () => signedStart({ expires: now() + 400 })],
    ['a kind we never send', () => signedStart({ kind: 'schedule' })],
    ['a nonce with a line break', () => signedStart({ nonce: 'a\nrun_now' })],
    ['a body that is not an object', () => ({ ...signedStart(), body: 'start' })],
  ])('answers 401 and starts nothing for %s', async (_case, start) => {
    const { out, status } = await deliver(start());
    expect(status).toBe(401);
    expect(out).toEqual({ noWebhookResponse: true });
  });

  it('answers 401 to a nonce it has already started with', async () => {
    const start = signedStart();
    expect((await deliver(start)).status).toBeUndefined();
    const again = await deliver(start);
    expect(again.status).toBe(401);
    expect(again.out).toEqual({ noWebhookResponse: true });
  });

  it('refuses every start while WAB_START_SECRET is not set', async () => {
    const start = signedStart();
    setEnv({ WAB_START_SECRET: undefined });
    const { out, status } = await deliver(start);
    expect(status).toBe(503);
    expect(out).toEqual({ noWebhookResponse: true });
  });
});
