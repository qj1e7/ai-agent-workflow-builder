import type {
  INodeType,
  INodeTypeDescription,
  IWebhookFunctions,
  IWebhookResponseData,
} from 'n8n-workflow';
import { answerSafely, isToken, refuse, signedBy } from '../signing';

/**
 * The trigger's path, and the only place it is decided. With `isFullPath: false` n8n registers
 * `POST /webhook/{node.webhookId}/start` (n8n-workflow's getNodeWebhookPath). Spike P7 confirms it
 * on a running n8n.
 */
export const START_PATH = 'start';

const KINDS = new Set(['run_now', 'test', 'retry']);
const MAX_LIFETIME_S = 300;
// The clocks of our API and n8n may differ by up to this much either way.
const CLOCK_SKEW_S = 60;

// A first filter only: n8n forgets it on restart. Our API, which issued each nonce for one run of
// one workflow, is the real guard.
const startedNonces = new Map<string, number>();

function rememberNonce(nonce: string, expires: number, now: number): boolean {
  for (const [seen, until] of startedNonces) if (until + CLOCK_SKEW_S < now) startedNonces.delete(seen);
  if (startedNonces.has(nonce)) return false;
  startedNonces.set(nonce, expires);
  return true;
}

export class StartFromPortal implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Start from the Portal',
    name: 'wabStartFromPortal',
    group: ['trigger'],
    version: 1,
    subtitle: 'Portal',
    description: 'Our block. Starts this workflow when someone presses Run now, Test run or Retry in the Portal.',
    defaults: { name: 'Start from the Portal' },
    inputs: [],
    outputs: ['main'],
    webhooks: [{ name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: START_PATH, isFullPath: false }],
    properties: [],
  };

  webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
    return Promise.resolve(answerSafely(this, answerStart));
  }
}

function answerStart(ctx: IWebhookFunctions): IWebhookResponseData {
  const secret = process.env.WAB_START_SECRET?.trim();
  if (!secret) return refuse(ctx, 503, 'This n8n cannot check starts: WAB_START_SECRET is not set.');
  const workflowId = ctx.getWorkflow().id;
  const { webhookId } = ctx.getNode();
  if (!isToken(workflowId) || !isToken(webhookId)) {
    return refuse(ctx, 503, 'This trigger has no workflow id or webhook id, so it cannot check starts.');
  }

  const body = ctx.getBodyData() as unknown;
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return refuse(ctx, 401, 'Not a signed start.');
  const { nonce, kind, expires } = body as { nonce?: unknown; kind?: unknown; expires?: unknown };
  if (!isToken(nonce) || typeof kind !== 'string' || !KINDS.has(kind)) {
    return refuse(ctx, 401, 'Not a signed start.');
  }
  if (typeof expires !== 'number' || !Number.isInteger(expires)) return refuse(ctx, 401, 'Not a signed start.');

  const signature = ctx.getHeaderData()['x-wab-signature'];
  // Signed for this workflow's own trigger, so a start for one workflow cannot start another.
  if (!signedBy(secret, [workflowId, webhookId, nonce, kind, expires], signature)) {
    return refuse(ctx, 401, 'The signature does not match.');
  }

  const now = Math.floor(Date.now() / 1000);
  if (expires + CLOCK_SKEW_S < now) return refuse(ctx, 401, 'This start has expired.');
  if (expires > now + MAX_LIFETIME_S + CLOCK_SKEW_S) return refuse(ctx, 401, 'This start lives too long.');
  if (!rememberNonce(nonce, expires, now)) return refuse(ctx, 401, 'This start was already used.');

  return { workflowData: [[{ json: { nonce, kind, workflow_id: workflowId } }]] };
}
