import type {
  IDataObject,
  IExecuteFunctions,
  IHttpRequestOptions,
  ILoadOptionsFunctions,
  INode,
  INodeExecutionData,
  IWebhookFunctions,
} from 'n8n-workflow';

export const API_URL = 'http://platform-api:8000';
export const NODE_KEY = 'node-key-for-tests';
export const START_SECRET = 'start-secret-for-tests';
export const RESUME_URL = 'http://n8n:5678/webhook-waiting/41?signature=resume-token';

export function setEnv(values: Record<string, string | undefined>): void {
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
}

export interface SentRequest {
  method: string | undefined;
  url: string;
  headers: IDataObject;
  qs: IDataObject | undefined;
  body: unknown;
}

type Answer = { statusCode: number; body: unknown } | Error;

/** Stands in for our API behind n8n's `helpers.httpRequest`, with n8n's own status handling. */
export class FakeApi {
  readonly sent: SentRequest[] = [];
  private answer: Answer = { statusCode: 200, body: {} };

  answers(statusCode: number, body: unknown): this {
    this.answer = { statusCode, body };
    return this;
  }

  fails(error: Error): this {
    this.answer = error;
    return this;
  }

  readonly httpRequest = (options: IHttpRequestOptions): Promise<unknown> => {
    this.sent.push({
      method: options.method,
      url: options.url,
      headers: options.headers ?? {},
      qs: options.qs,
      body: options.body,
    });
    const answer = this.answer;
    if (answer instanceof Error) return Promise.reject(answer);
    if (answer.statusCode >= 400 && !options.ignoreHttpStatusErrors) {
      return Promise.reject(new Error(`Request failed with status code ${answer.statusCode}`));
    }
    return Promise.resolve(options.returnFullResponse ? answer : answer.body);
  };
}

function node(name: string, type: string): INode {
  return { id: 'node-1', name, type, typeVersion: 1, position: [0, 0], parameters: {} };
}

export interface ExecuteRun {
  ctx: IExecuteFunctions;
  waits: Date[];
}

/**
 * An execution's custom data. n8n saves it with the execution's run data and hands it to the
 * resumed webhook, so an execute and its later wake share it (checked on n8n 2.42.6).
 */
export type CustomData = Record<string, string>;

function customDataOf(data: CustomData = {}) {
  return { set: (key: string, value: string) => (data[key] = value), get: (key: string) => data[key] };
}

export function executeContext(options: {
  api: FakeApi;
  customData?: CustomData;
  params?: IDataObject;
  input?: INodeExecutionData[];
  nodeName?: string;
  nodeType?: string;
  mode?: string;
}): ExecuteRun {
  const waits: Date[] = [];
  const params = options.params ?? {};
  const ctx = {
    getNode: () => node(options.nodeName ?? 'Block', options.nodeType ?? 'CUSTOM.block'),
    getNodeParameter: (name: string, _itemIndex: number, fallback?: unknown) => params[name] ?? fallback,
    getInputData: () => options.input ?? [{ json: { from: 'upstream' } }],
    getExecutionId: () => '41',
    getWorkflow: () => ({ id: 'wf-7', name: 'Release check', active: true }),
    getMode: () => options.mode ?? 'trigger',
    // n8n checks a wake against the execution's resume token, which only $execution.resumeUrl carries.
    evaluateExpression: (expression: string) => {
      if (expression !== '{{ $execution.resumeUrl }}') throw new Error(`unexpected expression ${expression}`);
      return RESUME_URL;
    },
    customData: customDataOf(options.customData),
    putExecutionToWait: (until: Date) => {
      waits.push(until);
      return Promise.resolve();
    },
    helpers: { httpRequest: options.api.httpRequest },
  };
  return { ctx: ctx as unknown as IExecuteFunctions, waits };
}

export interface WebhookCall {
  ctx: IWebhookFunctions;
  response: { status?: number; body?: unknown };
}

export function webhookContext(options: {
  body: unknown;
  headers?: IDataObject;
  executionId?: string;
  workflowId?: string;
  webhookId?: string;
  customData?: CustomData;
  failsWith?: Error;
}): WebhookCall {
  const response: WebhookCall['response'] = {};
  const res = {
    status(code: number) {
      response.status = code;
      return res;
    },
    json(body: unknown) {
      response.body = body;
      return res;
    },
  };
  const ctx = {
    getNode: () => ({ ...node('Block', 'CUSTOM.block'), webhookId: options.webhookId }),
    getWorkflow: () => ({ id: options.workflowId, name: 'Release check', active: true }),
    getBodyData: () => {
      if (options.failsWith) throw options.failsWith;
      return options.body;
    },
    getHeaderData: () => options.headers ?? {},
    getResponseObject: () => res,
    getExecutionId: () => options.executionId ?? '41',
    customData: customDataOf(options.customData),
  };
  return { ctx: ctx as unknown as IWebhookFunctions, response };
}

export function loadOptionsContext(api: FakeApi, current: IDataObject = {}): ILoadOptionsFunctions {
  const ctx = {
    getNode: () => node('Block', 'CUSTOM.block'),
    getCurrentNodeParameter: (name: string) => current[name],
    helpers: { httpRequest: api.httpRequest },
  };
  return ctx as unknown as ILoadOptionsFunctions;
}
