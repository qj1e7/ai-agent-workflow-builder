import type {
  IExecuteFunctions,
  ILoadOptionsFunctions,
  INodeExecutionData,
  INodePropertyOptions,
  INodeType,
  INodeTypeDescription,
} from 'n8n-workflow';
import { NodeOperationError } from 'n8n-workflow';
import { answerItems, callApi, loadOptions } from '../api';

const MAX_INPUT_BYTES = 8 * 1024;
const MAX_INPUTS_BYTES = 64 * 1024;

interface InputRow {
  name?: string;
  value?: unknown;
}

export class Agent implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Agent',
    name: 'wabAgent',
    group: ['transform'],
    version: 1,
    subtitle: '={{ $parameter["agent"] }}',
    description: 'Our block. Runs one of the team’s agent cards. It can propose changes, never make them.',
    defaults: { name: 'Agent' },
    inputs: ['main'],
    outputs: ['main'],
    properties: [
      {
        displayName: 'Agent',
        name: 'agent',
        type: 'options',
        noDataExpression: true,
        typeOptions: { loadOptionsMethod: 'getAgents' },
        default: '',
        description: 'One of the team’s agent cards, or one of the platform’s own agents',
      },
      {
        displayName: 'Inputs',
        name: 'inputs',
        type: 'fixedCollection',
        typeOptions: { multipleValues: true },
        placeholder: 'Add input',
        default: {},
        description: 'What the agent card asks for. Each value at most 8 KB, and 64 KB in all.',
        options: [
          {
            displayName: 'Input',
            name: 'input',
            values: [
              {
                displayName: 'Name',
                name: 'name',
                type: 'options',
                typeOptions: { loadOptionsMethod: 'getAgentInputs', loadOptionsDependsOn: ['agent'] },
                default: '',
              },
              { displayName: 'Value', name: 'value', type: 'string', default: '' },
            ],
          },
        ],
      },
    ],
  };

  methods = {
    loadOptions: {
      async getAgents(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
        return loadOptions(this, 'agents');
      },
      async getAgentInputs(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
        return loadOptions(this, 'agent_inputs', { agent: this.getCurrentNodeParameter('agent') as string });
      },
    },
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const agent = this.getNodeParameter('agent', 0) as string;
    const rows = (this.getNodeParameter('inputs', 0, {}) as { input?: InputRow[] }).input ?? [];
    const inputs: Record<string, string> = {};
    let total = 0;
    for (const { name, value } of rows) {
      if (!name) continue;
      const text = typeof value === 'string' ? value : JSON.stringify(value ?? '');
      const bytes = Buffer.byteLength(text, 'utf8');
      if (bytes > MAX_INPUT_BYTES) {
        throw new NodeOperationError(this.getNode(), `The input "${name}" is over 8 KB.`);
      }
      total += bytes;
      inputs[name] = text;
    }
    if (total > MAX_INPUTS_BYTES) throw new NodeOperationError(this.getNode(), 'The inputs are over 64 KB in all.');
    const answer = await callApi(this, 'calls/agent', { agent, inputs }, 120_000);
    return [answerItems(this.getNode(), answer)];
  }
}
