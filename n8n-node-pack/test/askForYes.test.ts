import { createHmac } from 'node:crypto';
import { NodeOperationError } from 'n8n-workflow';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AskForYes } from '../src/nodes/AskForYes.node';
import { API_URL, FakeApi, NODE_KEY, RESUME_URL, type CustomData, executeContext, setEnv, webhookContext } from './fake';

// No answer comes first: when webhook() throws, n8n runs output 0 (P7, Q14), so it must never be Yes.
const EXITS = ['No answer', 'Yes', 'No', 'Nothing to change'];

// The wake our API sends to the resume URL. Its mac is the contract: HMAC-SHA256 with the node key
// over the execution, the request and the decision, one per line.
function wake(decision: string, overrides: Record<string, string> = {}) {
  const body = { execution_id: '41', request_id: 'req-9f1c', decision, ...overrides };
  const mac = createHmac('sha256', NODE_KEY)
    .update(`${body.execution_id}\n${body.request_id}\n${body.decision}`)
    .digest('hex');
  return { ...body, mac };
}

// What the ask left in execution 41's custom data, as when request req-9f1c waits.
const waitingFor = (requestId = 'req-9f1c'): CustomData => ({ wab_waiting_request: requestId });

function exitTaken(workflowData: unknown[][] | undefined): string[] {
  return (workflowData ?? []).flatMap((items, i) => (items.length ? [EXITS[i]!] : []));
}

beforeEach(() => setEnv({ WAB_API_URL: API_URL, WAB_NODE_KEY: NODE_KEY }));
afterEach(() => setEnv({ WAB_API_URL: undefined, WAB_NODE_KEY: undefined }));

describe('Ask for a yes, asking', () => {
  it('has the four exits in order, and output 0 is not Yes', () => {
    const { outputNames, outputs } = new AskForYes().description;
    expect(outputNames).toEqual(EXITS);
    expect(outputs).toHaveLength(4);
    expect(outputNames?.[0]).not.toBe('Yes');
  });

  it("sends our API the resume URL with the execution's resume token, then waits with no time limit", async () => {
    const api = new FakeApi().answers(200, { status: 'waiting', request_id: 'req-9f1c' });
    const { ctx, waits } = executeContext({ api });
    const out = await new AskForYes().execute.call(ctx);
    expect(api.sent[0]?.body).toMatchObject({ resume_url: RESUME_URL });
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

  it('wakes only for the request our API says it is waiting on', async () => {
    const customData: CustomData = {};
    const api = new FakeApi().answers(200, { status: 'waiting', request_id: 'req-2' });
    await new AskForYes().execute.call(executeContext({ api, customData }).ctx);
    const earlier = webhookContext({ body: wake('yes', { request_id: 'req-1' }), customData });
    expect(await new AskForYes().webhook.call(earlier.ctx)).toEqual({ noWebhookResponse: true });
    expect(earlier.response.status).toBe(401);
    const current = webhookContext({ body: wake('yes', { request_id: 'req-2' }), customData });
    expect(exitTaken((await new AskForYes().webhook.call(current.ctx)).workflowData)).toEqual(['Yes']);
  });

  it.each([{ status: 'waiting' }, { status: 'waiting', request_id: 'req\n2' }])(
    'fails without waiting when our API names no request it waits on: %o',
    async (answer) => {
      const api = new FakeApi().answers(200, answer);
      const { ctx, waits } = executeContext({ api });
      await expect(new AskForYes().execute.call(ctx)).rejects.toThrow(NodeOperationError);
      expect(waits).toEqual([]);
    },
  );

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
    const { ctx, response } = webhookContext({ body: wake(decision), customData: waitingFor() });
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
    const { ctx, response } = webhookContext({ body: body(), customData: waitingFor() });
    const out = await new AskForYes().webhook.call(ctx);
    expect(response.status).toBe(401);
    expect(out).toEqual({ noWebhookResponse: true });
  });

  it('refuses every wake while WAB_NODE_KEY is not set', async () => {
    const body = wake('yes');
    setEnv({ WAB_NODE_KEY: undefined });
    const { ctx, response } = webhookContext({ body, customData: waitingFor() });
    expect(await new AskForYes().webhook.call(ctx)).toEqual({ noWebhookResponse: true });
    expect(response.status).toBe(401);
  });

  it('a wake whose check throws gets 500 and picks no exit, so n8n cannot fall through to output 0', async () => {
    const { ctx, response } = webhookContext({ body: wake('yes'), customData: waitingFor(), failsWith: new Error('boom') });
    expect(await new AskForYes().webhook.call(ctx)).toEqual({ noWebhookResponse: true });
    expect(response.status).toBe(500);
  });

  it('a signed decision it does not know picks no exit', async () => {
    const { ctx, response } = webhookContext({ body: wake('maybe'), customData: waitingFor() });
    expect(await new AskForYes().webhook.call(ctx)).toEqual({ noWebhookResponse: true });
    expect(response.status).toBe(400);
  });
});
