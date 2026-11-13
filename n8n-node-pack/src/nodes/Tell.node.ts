import type { IExecuteFunctions, INodeExecutionData, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { callApi } from '../api';

export class Tell implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Tell',
    name: 'wabTell',
    group: ['output'],
    version: 1,
    subtitle: '={{ {"channel": "Teams", "email": "Email", "both": "Teams and email"}[$parameter["where"]] }}',
    description: 'Our block. Tells the team what the run found, in Teams or by email. It changes nothing.',
    defaults: { name: 'Tell' },
    inputs: ['main'],
    outputs: ['main'],
    properties: [
      {
        displayName: 'Where',
        name: 'where',
        type: 'options',
        noDataExpression: true,
        options: [
          { name: 'The Team’s Teams Channel', value: 'channel' },
          { name: 'The Email List', value: 'email' },
          { name: 'Both', value: 'both' },
        ],
        default: 'channel',
        description: 'The channel and the email list are set in the Portal',
      },
      {
        displayName: 'What',
        name: 'what',
        type: 'options',
        noDataExpression: true,
        options: [
          { name: 'The Run’s Result', value: 'result' },
          { name: 'Only When There Is Something to Report', value: 'only_when_something_to_report' },
        ],
        default: 'result',
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    await callApi(this, 'calls/tell', {
      where: this.getNodeParameter('where', 0),
      what: this.getNodeParameter('what', 0),
    });
    return [this.getInputData()];
  }
}
