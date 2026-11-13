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

const MAX_QUERY_CHARS = 2000;

export class Read implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Read',
    name: 'wabRead',
    group: ['input'],
    version: 1,
    subtitle: '={{ {"github_releases": "GitHub", "jira_tickets": "Jira", "confluence_page": "Confluence"}[$parameter["source"]] }}',
    description: 'Our block. Reads from GitHub, Jira or Confluence, only where the Portal allows. It can’t change anything.',
    defaults: { name: 'Read' },
    inputs: ['main'],
    outputs: ['main'],
    properties: [
      {
        displayName: 'Source',
        name: 'source',
        type: 'options',
        noDataExpression: true,
        options: [
          { name: 'GitHub Releases', value: 'github_releases' },
          { name: 'Jira Tickets', value: 'jira_tickets' },
          { name: 'Confluence Page', value: 'confluence_page' },
        ],
        default: 'github_releases',
      },
      {
        displayName: 'Place',
        name: 'place',
        type: 'options',
        noDataExpression: true,
        typeOptions: { loadOptionsMethod: 'getPlaces', loadOptionsDependsOn: ['source'] },
        default: '',
        description: 'A watched repository, an allowed Jira project or an allowed Confluence page, as set in the Portal',
      },
      {
        displayName: 'Query',
        name: 'query',
        type: 'string',
        displayOptions: { show: { source: ['jira_tickets'] } },
        default: '',
        description: 'Which tickets to read, in JQL. At most 2,000 characters.',
      },
    ],
  };

  methods = {
    loadOptions: {
      async getPlaces(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
        return loadOptions(this, 'places', { source: this.getCurrentNodeParameter('source') as string });
      },
    },
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const source = this.getNodeParameter('source', 0) as string;
    const place = this.getNodeParameter('place', 0) as string;
    const query = source === 'jira_tickets' ? (this.getNodeParameter('query', 0, '') as string) : null;
    if (query !== null && query.length > MAX_QUERY_CHARS) {
      throw new NodeOperationError(this.getNode(), 'A Jira query can be at most 2,000 characters.');
    }
    const answer = await callApi(this, 'calls/read', { source, place, query });
    return [answerItems(this.getNode(), answer)];
  }
}
