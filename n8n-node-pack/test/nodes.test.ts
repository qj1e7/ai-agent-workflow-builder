import { NodeOperationError } from 'n8n-workflow';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Agent } from '../src/nodes/Agent.node';
import { MakeApprovedChanges } from '../src/nodes/MakeApprovedChanges.node';
import { ProposeChange } from '../src/nodes/ProposeChange.node';
import { Read } from '../src/nodes/Read.node';
import { ReportFailure } from '../src/nodes/ReportFailure.node';
import { Tell } from '../src/nodes/Tell.node';
import { API_URL, FakeApi, NODE_KEY, executeContext, loadOptionsContext, setEnv } from './fake';

beforeEach(() => setEnv({ WAB_API_URL: API_URL, WAB_NODE_KEY: NODE_KEY }));
afterEach(() => setEnv({ WAB_API_URL: undefined, WAB_NODE_KEY: undefined }));

describe('Read', () => {
  it('passes on each item our API read', async () => {
    const api = new FakeApi().answers(200, {
      items: [
        { kind: 'github_release', id: 'v1.2.0', fields: { name: 'LangGraph 1.2.0' } },
        { kind: 'github_release', id: 'v1.1.9', fields: { name: 'LangGraph 1.1.9' } },
      ],
    });
    const { ctx } = executeContext({ api, params: { source: 'github_releases', place: 'langchain-ai/langgraph' } });
    expect(await new Read().execute.call(ctx)).toEqual([
      [
        { json: { kind: 'github_release', id: 'v1.2.0', fields: { name: 'LangGraph 1.2.0' } } },
        { json: { kind: 'github_release', id: 'v1.1.9', fields: { name: 'LangGraph 1.1.9' } } },
      ],
    ]);
  });

  it('sends no query outside Jira', async () => {
    const api = new FakeApi().answers(200, { items: [] });
    const params = { source: 'github_releases', place: 'langchain-ai/langgraph', query: 'left over' };
    await new Read().execute.call(executeContext({ api, params }).ctx);
    expect(api.sent[0]?.body).toMatchObject({ source: 'github_releases', query: null });
  });

  it('refuses a Jira query over 2,000 characters before calling', async () => {
    const api = new FakeApi().answers(200, { items: [] });
    const params = { source: 'jira_tickets', place: 'MOCK', query: 'x'.repeat(2001) };
    await expect(new Read().execute.call(executeContext({ api, params }).ctx)).rejects.toThrow(/2,000/);
    expect(api.sent).toEqual([]);
  });

  it("lists the places for the chosen source from our API's options", async () => {
    const api = new FakeApi().answers(200, {
      options: [
        { id: 'MOCK', name: 'MOCK (practice Jira)' },
        { id: 'OPS', name: 'OPS' },
      ],
    });
    const options = await new Read().methods.loadOptions.getPlaces.call(
      loadOptionsContext(api, { source: 'jira_tickets' }),
    );
    expect(options).toEqual([
      { name: 'MOCK (practice Jira)', value: 'MOCK' },
      { name: 'OPS', value: 'OPS' },
    ]);
    expect(api.sent).toEqual([
      {
        method: 'GET',
        url: `${API_URL}/internal/v1/n8n/options`,
        headers: { 'X-Wab-Node-Key': NODE_KEY },
        qs: { kind: 'places', source: 'jira_tickets' },
        body: undefined,
      },
    ]);
  });
});

describe('Agent', () => {
  const agentParams = (value: string) => ({ agent: 'version-checker', inputs: { input: [{ name: 'notes', value }] } });

  it("passes on the agent's result items", async () => {
    const api = new FakeApi().answers(200, { items: [{ summary: 'One newer release', newer: true }] });
    const { ctx } = executeContext({ api, params: agentParams('short') });
    expect(await new Agent().execute.call(ctx)).toEqual([[{ json: { summary: 'One newer release', newer: true } }]]);
  });

  it('refuses an input over 8 KB before calling', async () => {
    const api = new FakeApi().answers(200, { items: [] });
    const { ctx } = executeContext({ api, params: agentParams('x'.repeat(8 * 1024 + 1)) });
    await expect(new Agent().execute.call(ctx)).rejects.toThrow(/8 KB/);
    expect(api.sent).toEqual([]);
  });

  it('refuses inputs over 64 KB in all before calling', async () => {
    const api = new FakeApi().answers(200, { items: [] });
    const input = Array.from({ length: 9 }, (_, i) => ({ name: `part${i}`, value: 'x'.repeat(8 * 1024) }));
    const { ctx } = executeContext({ api, params: { agent: 'version-checker', inputs: { input } } });
    await expect(new Agent().execute.call(ctx)).rejects.toThrow(/64 KB/);
    expect(api.sent).toEqual([]);
  });

  it('sends an input that is not text as JSON', async () => {
    const api = new FakeApi().answers(200, { items: [] });
    const input = [
      { name: 'versions', value: { ours: '1.1.0' } },
      { name: 'count', value: 5 },
    ];
    await new Agent().execute.call(executeContext({ api, params: { agent: 'version-checker', inputs: { input } } }).ctx);
    expect(api.sent[0]?.body).toMatchObject({ inputs: { versions: '{"ours":"1.1.0"}', count: '5' } });
  });

  it("lists the chosen agent's declared inputs", async () => {
    const api = new FakeApi().answers(200, { options: [{ id: 'repo', name: 'Repository' }] });
    const options = await new Agent().methods.loadOptions.getAgentInputs.call(
      loadOptionsContext(api, { agent: 'version-checker' }),
    );
    expect(options).toEqual([{ name: 'Repository', value: 'repo' }]);
    expect(api.sent[0]?.qs).toEqual({ kind: 'agent_inputs', agent: 'version-checker' });
  });
});

describe.each([
  ['Propose a change', new ProposeChange(), { action: 'jira.create_ticket', place: 'MOCK', title: 't', body: 'b', subject: 's' }],
  ['Tell', new Tell(), { where: 'both', what: 'only_when_something_to_report' }],
])('%s', (_name, node, params) => {
  it('passes its input on unchanged', async () => {
    const api = new FakeApi().answers(200, { status: 'added' });
    const input = [{ json: { summary: 'One newer release' } }, { json: { summary: 'Another' } }];
    const { ctx } = executeContext({ api, params, input });
    expect(await node.execute.call(ctx)).toEqual([input]);
  });
});

describe('Make the approved changes', () => {
  it('passes on what was made', async () => {
    const results = [{ action: 'jira.create_ticket', key: 'MOCK-12' }];
    const api = new FakeApi().answers(200, { made: 1, of: 1, results });
    const { ctx } = executeContext({ api });
    expect(await new MakeApprovedChanges().execute.call(ctx)).toEqual([[{ json: { made: 1, of: 1, results } }]]);
  });

  it('fails the block when only some changes were made, so the error workflow fires', async () => {
    const api = new FakeApi().answers(200, { made: 2, of: 3, results: [] });
    const { ctx } = executeContext({ api });
    await expect(new MakeApprovedChanges().execute.call(ctx)).rejects.toSatisfy(
      (e) => e instanceof NodeOperationError && e.message === '2 of 3 made',
    );
  });
});

describe('Report a failure', () => {
  it('ends the error workflow with nothing to pass on', async () => {
    const api = new FakeApi().answers(200, { status: 'recorded' });
    const input = [{ json: { execution: { id: '40', mode: 'trigger', error: { message: 'boom' } }, workflow: { id: 'wf-7' } } }];
    const { ctx } = executeContext({ api, input });
    expect(await new ReportFailure().execute.call(ctx)).toEqual([]);
  });

  it('sends at most 2 KB of the error and of the workflow name', async () => {
    const api = new FakeApi().answers(200, {});
    const json = { execution: { id: '40', error: { message: 'x'.repeat(5000) } }, workflow: { id: 'wf-7', name: 'é'.repeat(2000) } };
    await new ReportFailure().execute.call(executeContext({ api, input: [{ json }] }).ctx);
    const body = api.sent[0]?.body as { error_message: string; failed_workflow_name: string };
    expect(body.error_message).toBe('x'.repeat(2048));
    expect(body.failed_workflow_name).toBe('é'.repeat(1024));
  });

  it('sends nulls for what the Error Trigger left out', async () => {
    const api = new FakeApi().answers(200, {});
    const { ctx } = executeContext({ api, input: [{ json: { execution: { id: '40' }, workflow: { id: 'wf-7' } } }] });
    await new ReportFailure().execute.call(ctx);
    expect(api.sent[0]?.body).toMatchObject({
      failed_execution_id: '40',
      failed_mode: null,
      retry_of: null,
      last_node_executed: null,
      error_message: null,
      failed_workflow_id: 'wf-7',
      failed_workflow_name: null,
    });
  });
});
