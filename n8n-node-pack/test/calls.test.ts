import type { IDataObject, INodeType } from 'n8n-workflow';
import { NodeOperationError } from 'n8n-workflow';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Agent } from '../src/nodes/Agent.node';
import { AskForYes } from '../src/nodes/AskForYes.node';
import { MakeApprovedChanges } from '../src/nodes/MakeApprovedChanges.node';
import { ProposeChange } from '../src/nodes/ProposeChange.node';
import { Read } from '../src/nodes/Read.node';
import { ReportFailure } from '../src/nodes/ReportFailure.node';
import { Tell } from '../src/nodes/Tell.node';
import { API_URL, FakeApi, NODE_KEY, RESUME_URL, executeContext, setEnv } from './fake';

const FIXED = { execution_id: '41', workflow_id: 'wf-7', node_name: 'Block', mode: 'trigger' };

const ERROR_TRIGGER_ITEM = {
  execution: {
    id: '40',
    url: 'http://n8n:5678/workflow/wf-7/executions/40',
    retryOf: '39',
    error: { message: 'GitHub did not answer', stack: 'Error: GitHub did not answer\n    at Read' },
    lastNodeExecuted: 'Read release',
    mode: 'trigger',
  },
  workflow: { id: 'wf-7', name: 'Release check' },
};

interface Case {
  node: INodeType;
  path: string;
  params: IDataObject;
  sends: IDataObject;
  answer: IDataObject;
  input?: IDataObject;
}

// Each block's own fields, plus the fixed ones every call carries. Nothing else may be sent.
const CASES: Record<string, Case> = {
  Read: {
    node: new Read(),
    path: 'calls/read',
    params: { source: 'jira_tickets', place: 'MOCK', query: 'status = Open' },
    sends: { ...FIXED, source: 'jira_tickets', place: 'MOCK', query: 'status = Open' },
    answer: { items: [] },
  },
  Agent: {
    node: new Agent(),
    path: 'calls/agent',
    params: { agent: 'version-checker', inputs: { input: [{ name: 'repo', value: 'langchain-ai/langgraph' }] } },
    sends: { ...FIXED, agent: 'version-checker', inputs: { repo: 'langchain-ai/langgraph' } },
    answer: { items: [] },
  },
  'Propose a change': {
    node: new ProposeChange(),
    path: 'calls/propose',
    params: {
      action: 'jira.create_ticket',
      place: 'MOCK',
      title: 'Update LangGraph to 1.2.0',
      body: 'A newer release is out.',
      subject: 'langgraph 1.2.0',
    },
    sends: {
      ...FIXED,
      action: 'jira.create_ticket',
      place: 'MOCK',
      title: 'Update LangGraph to 1.2.0',
      body: 'A newer release is out.',
      subject: 'langgraph 1.2.0',
    },
    answer: {},
  },
  'Ask for a yes': {
    node: new AskForYes(),
    path: 'calls/ask',
    params: {},
    sends: { ...FIXED, resume_url: RESUME_URL },
    answer: { status: 'waiting', request_id: 'req-1' },
  },
  'Make the approved changes': {
    node: new MakeApprovedChanges(),
    path: 'calls/write',
    params: {},
    sends: { ...FIXED },
    answer: { made: 1, of: 1, results: [] },
  },
  Tell: {
    node: new Tell(),
    path: 'calls/tell',
    params: { where: 'channel', what: 'result' },
    sends: { ...FIXED, where: 'channel', what: 'result' },
    answer: {},
  },
  'Report a failure': {
    node: new ReportFailure(),
    path: 'failures',
    params: {},
    input: ERROR_TRIGGER_ITEM,
    sends: {
      ...FIXED,
      failed_execution_id: '40',
      failed_mode: 'trigger',
      retry_of: '39',
      last_node_executed: 'Read release',
      error_message: 'GitHub did not answer',
      failed_workflow_id: 'wf-7',
      failed_workflow_name: 'Release check',
    },
    answer: {},
  },
};

function run(c: Case, api: FakeApi) {
  const { ctx } = executeContext({ api, params: c.params, input: c.input ? [{ json: c.input }] : undefined });
  return c.node.execute!.call(ctx);
}

beforeEach(() => setEnv({ WAB_API_URL: API_URL, WAB_NODE_KEY: NODE_KEY }));
afterEach(() => setEnv({ WAB_API_URL: undefined, WAB_NODE_KEY: undefined }));

describe.each(Object.entries(CASES))('%s', (_name, c) => {
  it('calls only our API, with the node key and only its fixed fields', async () => {
    const api = new FakeApi().answers(200, c.answer);
    await run(c, api);
    expect(api.sent).toEqual([
      {
        method: 'POST',
        url: `${API_URL}/internal/v1/n8n/${c.path}`,
        headers: { 'X-Wab-Node-Key': NODE_KEY },
        qs: undefined,
        body: c.sends,
      },
    ]);
  });

  it.each([['WAB_API_URL'], ['WAB_NODE_KEY']])('makes no call without %s', async (name) => {
    setEnv({ [name]: undefined });
    const api = new FakeApi().answers(200, c.answer);
    await expect(run(c, api)).rejects.toThrow(NodeOperationError);
    expect(api.sent).toEqual([]);
  });

  it("turns a refusal into a node error in our API's own words", async () => {
    const api = new FakeApi().answers(409, { detail: 'No yes for this run' });
    await expect(run(c, api)).rejects.toSatisfy(
      (e) => e instanceof NodeOperationError && e.message === 'No yes for this run',
    );
  });

  it('names the status when a refusal has no words', async () => {
    const api = new FakeApi().answers(422, { detail: [{ loc: ['body'], msg: 'bad' }] });
    await expect(run(c, api)).rejects.toThrow(/HTTP 422/);
  });

  it('throws on a server error so n8n can retry', async () => {
    const api = new FakeApi().answers(503, { detail: 'down' });
    await expect(run(c, api)).rejects.toThrow(/HTTP 503/);
  });

  it('throws when our API cannot be reached, naming only the error code', async () => {
    const api = new FakeApi().fails(Object.assign(new Error('connect ECONNREFUSED 10.1.2.3:8000'), { code: 'ECONNREFUSED' }));
    await expect(run(c, api)).rejects.toSatisfy(
      (e) =>
        e instanceof NodeOperationError &&
        /did not answer/.test(e.message) &&
        e.description === 'ECONNREFUSED' &&
        !`${e.message} ${e.description}`.includes('10.1.2.3'),
    );
  });

  it('throws on an answer that is a list, not an object', async () => {
    const api = new FakeApi().answers(200, [c.answer]);
    await expect(run(c, api)).rejects.toThrow(/cannot read/);
  });
});

describe('an answer with no body', () => {
  it('is an empty answer, not an error', async () => {
    const api = new FakeApi().answers(204, '');
    expect(await run(CASES.Tell!, api)).toEqual([[{ json: { from: 'upstream' } }]]);
  });
});

describe('the address', () => {
  it('ignores a trailing slash in WAB_API_URL', async () => {
    setEnv({ WAB_API_URL: `${API_URL}/` });
    const api = new FakeApi().answers(200, {});
    await run(CASES.Tell!, api);
    expect(api.sent[0]?.url).toBe(`${API_URL}/internal/v1/n8n/calls/tell`);
  });

  it('refuses a WAB_API_URL that is not http or https', async () => {
    setEnv({ WAB_API_URL: 'file:///etc/passwd' });
    const api = new FakeApi().answers(200, {});
    await expect(run(CASES.Tell!, api)).rejects.toThrow(/http/);
    expect(api.sent).toEqual([]);
  });

  it('has no field in any block for an address or a key', () => {
    for (const c of Object.values(CASES)) {
      const names = c.node.description.properties.map((p) => p.name.toLowerCase());
      expect(names.filter((n) => /url|address|host|key|token|credential/.test(n))).toEqual([]);
      expect(c.node.description.credentials ?? []).toEqual([]);
    }
  });
});
