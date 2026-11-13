import type {
  IDataObject,
  IExecuteFunctions,
  IHttpRequestOptions,
  ILoadOptionsFunctions,
  INode,
  INodeExecutionData,
  INodePropertyOptions,
} from 'n8n-workflow';
import { NodeOperationError } from 'n8n-workflow';

export const NODE_KEY_HEADER = 'X-Wab-Node-Key';

export type CallPath =
  | 'calls/read'
  | 'calls/agent'
  | 'calls/propose'
  | 'calls/ask'
  | 'calls/write'
  | 'calls/tell'
  | 'failures';

interface ApiEnv {
  base: string;
  key: string;
}

interface FullResponse {
  statusCode: number;
  body: unknown;
}

function apiEnv(node: INode): ApiEnv {
  const url = process.env.WAB_API_URL?.trim();
  const key = process.env.WAB_NODE_KEY?.trim();
  if (!url || !key) {
    throw new NodeOperationError(node, 'This n8n is not connected to our platform: WAB_API_URL or WAB_NODE_KEY is not set.');
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new NodeOperationError(node, 'WAB_API_URL is not a web address.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new NodeOperationError(node, 'WAB_API_URL must start with http:// or https://.');
  }
  return { base: `${parsed.origin}${parsed.pathname.replace(/\/+$/, '')}/internal/v1/n8n`, key };
}

async function send(
  helpers: IExecuteFunctions['helpers'] | ILoadOptionsFunctions['helpers'],
  node: INode,
  request: IHttpRequestOptions,
): Promise<IDataObject> {
  let response: FullResponse;
  try {
    response = (await helpers.httpRequest({
      ...request,
      json: true,
      returnFullResponse: true,
      ignoreHttpStatusErrors: true,
    })) as FullResponse;
  } catch (error) {
    // Only the code: the message names hosts and addresses that anyone who opens the editor would see.
    const code = (error as { code?: unknown } | null)?.code;
    throw new NodeOperationError(node, 'Our platform did not answer. n8n tries again if this block has retries on.', {
      description: typeof code === 'string' ? code : 'No answer',
    });
  }
  const { statusCode, body } = response;
  if (statusCode >= 200 && statusCode < 300) {
    if (body === undefined || body === '') return {};
    if (body === null || typeof body !== 'object' || Array.isArray(body)) {
      throw new NodeOperationError(node, 'Our platform sent an answer this block cannot read.');
    }
    return body as IDataObject;
  }
  // n8n's retryOnFail retries every error, a refusal included, and a node cannot opt out. So a
  // refused call is sent again up to three times, and our API must refuse it the same way each time.
  if (statusCode >= 400 && statusCode < 500) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new NodeOperationError(
      node,
      typeof detail === 'string' && detail ? detail : `Our platform refused this step (HTTP ${statusCode}).`,
    );
  }
  throw new NodeOperationError(node, `Our platform could not do this step (HTTP ${statusCode}). n8n tries again if this block has retries on.`);
}

/** The fields every call carries, so our API can tell which execution and block is calling. */
function fixedFields(ctx: IExecuteFunctions): IDataObject {
  return {
    execution_id: ctx.getExecutionId(),
    workflow_id: ctx.getWorkflow().id ?? null,
    node_name: ctx.getNode().name,
    mode: ctx.getMode(),
  };
}

export async function callApi(
  ctx: IExecuteFunctions,
  path: CallPath,
  fields: IDataObject,
  timeoutMs = 60_000,
): Promise<IDataObject> {
  const node = ctx.getNode();
  const env = apiEnv(node);
  return send(ctx.helpers, node, {
    method: 'POST',
    url: `${env.base}/${path}`,
    headers: { [NODE_KEY_HEADER]: env.key },
    body: { ...fields, ...fixedFields(ctx) },
    timeout: timeoutMs,
  });
}

export type OptionKind = 'places' | 'agents' | 'agent_inputs' | 'write_actions';

/** The editor's lists. Our API answers with names and ids from the Portal's settings, never run data. */
export async function loadOptions(
  ctx: ILoadOptionsFunctions,
  kind: OptionKind,
  filter: Record<string, string> = {},
): Promise<INodePropertyOptions[]> {
  const node = ctx.getNode();
  const env = apiEnv(node);
  const body = await send(ctx.helpers, node, {
    method: 'GET',
    url: `${env.base}/options`,
    qs: { kind, ...filter },
    headers: { [NODE_KEY_HEADER]: env.key },
    timeout: 15_000,
  });
  const options = Array.isArray(body.options) ? body.options : [];
  return options.flatMap((option) => {
    const { id, name } = (option ?? {}) as { id?: unknown; name?: unknown };
    return typeof id === 'string' && typeof name === 'string' ? [{ name, value: id }] : [];
  });
}

/** Read and Agent answer with `items`, each passed on as one n8n item. */
export function answerItems(node: INode, answer: IDataObject): INodeExecutionData[] {
  const { items } = answer;
  if (!Array.isArray(items)) throw new NodeOperationError(node, 'Our platform sent an answer this block cannot read.');
  return items.map((json) => {
    if (json === null || typeof json !== 'object' || Array.isArray(json)) {
      throw new NodeOperationError(node, 'Our platform sent an answer this block cannot read.');
    }
    return { json: json as IDataObject };
  });
}
