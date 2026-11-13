import type {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
  IWebhookFunctions,
  IWebhookResponseData,
} from 'n8n-workflow';
import { NodeOperationError } from 'n8n-workflow';
import { callApi } from '../api';
import { isToken, refuse, signedBy } from '../signing';

// Our API keeps the clock and wakes the execution with no_answer when the request expires.
const WAIT_WITHOUT_LIMIT = new Date('3000-01-01T00:00:00.000Z');

/** The exits, in order. The wake's decision and the ask's answer each pick one by name. */
const EXITS = {
  yes: 'Yes',
  no: 'No',
  no_answer: 'No answer',
  nothing_to_change: 'Nothing to change',
} as const;
type Exit = keyof typeof EXITS;
const EXIT_ORDER = Object.keys(EXITS) as Exit[];
type Decision = Exclude<Exit, 'nothing_to_change'>;
const isDecision = (value: string): value is Decision => value === 'yes' || value === 'no' || value === 'no_answer';

function leaveBy(exit: Exit, items: INodeExecutionData[]): INodeExecutionData[][] {
  return EXIT_ORDER.map((e) => (e === exit ? items : []));
}

export class AskForYes implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Ask for a yes',
    name: 'wabAskForYes',
    group: ['transform'],
    version: 1,
    subtitle: 'Teams',
    description: 'Our block. Asks any Approver except the person who started the run, in Teams.',
    defaults: { name: 'Ask for a yes' },
    inputs: ['main'],
    outputs: ['main', 'main', 'main', 'main'],
    outputNames: EXIT_ORDER.map((e) => EXITS[e]),
    webhooks: [{ name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: '', restartWebhook: true }],
    properties: [],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const answer = await callApi(this, 'calls/ask', { resume_url: this.getSignedResumeUrl() });
    if (answer.status === 'nothing_to_change') return leaveBy('nothing_to_change', this.getInputData());
    if (answer.status !== 'waiting') {
      throw new NodeOperationError(this.getNode(), 'Our platform gave an answer to the ask that this block does not know.');
    }
    await this.putExecutionToWait(WAIT_WITHOUT_LIMIT);
    return EXIT_ORDER.map(() => []);
  }

  // The decision only picks an exit. Make the approved changes checks our API's own records.
  webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
    return Promise.resolve(answerWake(this));
  }
}

function answerWake(ctx: IWebhookFunctions): IWebhookResponseData {
  const key = process.env.WAB_NODE_KEY?.trim();
  const body = ctx.getBodyData() as unknown;
  if (!key || body === null || typeof body !== 'object' || Array.isArray(body)) {
    return refuse(ctx, 401, 'Not a signed answer.');
  }
  const { execution_id, request_id, decision, mac } = body as Record<string, unknown>;
  if (!isToken(execution_id) || !isToken(request_id) || !isToken(decision)) {
    return refuse(ctx, 401, 'Not a signed answer.');
  }
  if (execution_id !== ctx.getExecutionId() || !signedBy(key, [execution_id, request_id, decision], mac)) {
    return refuse(ctx, 401, 'Not a signed answer.');
  }
  if (!isDecision(decision)) return refuse(ctx, 400, 'Not a decision this block knows.');
  return { workflowData: leaveBy(decision, [{ json: { request_id, decision } }]) };
}
