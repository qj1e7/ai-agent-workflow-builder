import { createHmac } from 'node:crypto';
import { NodeOperationError } from 'n8n-workflow';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AskForYes } from '../src/nodes/AskForYes.node';
import { API_URL, FakeApi, NODE_KEY, executeContext, setEnv, webhookContext } from './fake';

const EXITS = ['Yes', 'No', 'No answer', 'Nothing to change'];

// The wake our API sends to the resume URL. Its mac is the contract: HMAC-SHA256 with the node key
// over the execution, the request and the decision, one per line.
function wake(decision: string, overrides: Record<string, string> = {}) {
  const body = { execution_id: '41', request_id: 'req-9f1c', decision, ...overrides };
  const mac = createHmac('sha256', NODE_KEY)
    .update(`${body.execution_id}\n${body.request_id}\n${body.decision}`)
    .digest('hex');
  return { ...body, mac };
}

function exitTaken(workflowData: unknown[][] | undefined): string[] {
  return (workflowData ?? []).flatMap((items, i) => (items.length ? [EXITS[i]!] : []));
}

beforeEach(() => setEnv({ WAB_API_URL: API_URL, WAB_NODE_KEY: NODE_KEY }));
afterEach(() => setEnv({ WAB_API_URL: undefined, WAB_NODE_KEY: undefined }));

describe('Ask for a yes, asking', () => {
  it('has the four exits in order', () => {
    expect(new AskForYes().description.outputNames).toEqual(EXITS);
  });

  it('sends our API the signed resume URL, then waits with no time limit', async () => {
    const api = new FakeApi().answers(200, { status: 'waiting' });
    const { ctx, waits } = executeContext({ api });
    const out = await new AskForYes().execute.call(ctx);
    expect(api.sent[0]?.body).toMatchObject({ resume_url: 'http://n8n:5678/webhook-waiting/41/node-1?signature=abc' });
    expect(waits).toEqual([new Date('3000-01-01T00:00:00.000Z')]);
    expect(exitTaken(out)).toEqual([]);
  });

  it('leaves by Nothing to change without waiting when the proposal is empty', async () => {
    const api = new FakeApi().answers(200, { status: 'nothing_to_change' });
    const input = [{ json: { summary: 'No newer release' } }];
    const { ctx, waits } = executeContext({ api, input });
    const out = await new AskForYes().execute.call(ctx);
    expect(waits).toEqual([]);
    expect(out).toEqual([[], [], [], input]);
  });

  it('fails rather than guess at an answer it does not know', async () => {
    const api = new FakeApi().answers(200, { status: 'approved' });
    const { ctx, waits } = executeContext({ api });
    await expect(new AskForYes().execute.call(ctx)).rejects.toThrow(NodeOperationError);
    expect(waits).toEqual([]);
  });
});

describe('Ask for a yes, woken', () => {
  it.each([
    ['yes', 'Yes'],
    ['no', 'No'],
    ['no_answer', 'No answer'],
  ])('a signed %s takes the %s exit only', async (decision, exit) => {
    const { ctx, response } = webhookContext({ body: wake(decision) });
    const out = await new AskForYes().webhook.call(ctx);
    expect(exitTaken(out.workflowData)).toEqual([exit]);
    expect(out.workflowData?.flat()).toEqual([{ json: { request_id: 'req-9f1c', decision } }]);
    expect(response.status).toBeUndefined();
  });

  it.each([
    ['no mac', () => ({ execution_id: '41', request_id: 'req-9f1c', decision: 'yes' })],
    ['a wrong mac', () => ({ ...wake('yes'), mac: '0'.repeat(64) })],
    ['a mac for a different decision', () => ({ ...wake('no'), decision: 'yes' })],
    ['a mac for another execution', () => wake('yes', { execution_id: '99' })],
    ['a body that is not an object', () => 'yes'],
  ])('a wake with %s gets 401 and picks no exit', async (_case, body) => {
    const { ctx, response } = webhookContext({ body: body() });
    const out = await new AskForYes().webhook.call(ctx);
    expect(response.status).toBe(401);
    expect(out).toEqual({ noWebhookResponse: true });
  });

  it('refuses every wake while WAB_NODE_KEY is not set', async () => {
    const body = wake('yes');
    setEnv({ WAB_NODE_KEY: undefined });
    const { ctx, response } = webhookContext({ body });
    expect(await new AskForYes().webhook.call(ctx)).toEqual({ noWebhookResponse: true });
    expect(response.status).toBe(401);
  });

  it('a signed decision it does not know picks no exit', async () => {
    const { ctx, response } = webhookContext({ body: wake('maybe') });
    expect(await new AskForYes().webhook.call(ctx)).toEqual({ noWebhookResponse: true });
    expect(response.status).toBe(400);
  });
});
