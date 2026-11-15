import type {
  IExecuteFunctions,
  ILoadOptionsFunctions,
  INodeExecutionData,
  INodePropertyOptions,
  INodeType,
  INodeTypeDescription,
} from 'n8n-workflow';
import { callApi, loadOptions } from '../api';

export class ProposeChange implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Propose a change',
    name: 'wabProposeChange',
    group: ['transform'],
    version: 1,
    subtitle: '={{ $parameter["action"] }}',
    description: 'Our block. Adds a change to the run’s proposal. Nothing changes until an Approver says yes.',
    defaults: { name: 'Propose a change' },
    inputs: ['main'],
    outputs: ['main'],
    properties: [
      {
        displayName: 'Change',
        name: 'action',
        type: 'options',
        noDataExpression: true,
        typeOptions: { loadOptionsMethod: 'getWriteActions' },
        default: '',
      },
      {
        displayName: 'Place',
        name: 'place',
        type: 'options',
        noDataExpression: true,
        typeOptions: { loadOptionsMethod: 'getPlaces', loadOptionsDependsOn: ['action'] },
        default: '',
        description: 'An allowed place for this change, as set in the Portal',
      },
      { displayName: 'Title', name: 'title', type: 'string', default: '' },
      { displayName: 'Details', name: 'body', type: 'string', typeOptions: { rows: 4 }, default: '' },
      {
        displayName: 'About',
        name: 'subject',
        type: 'string',
        default: '',
        description: 'What the change is about, such as "langgraph 1.2.0", so the same change is never made twice',
      },
    ],
  };

  methods = {
    loadOptions: {
      async getWriteActions(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
        return loadOptions(this, 'write_actions');
      },
      async getPlaces(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
        return loadOptions(this, 'places', { action: this.getCurrentNodeParameter('action') as string });
      },
    },
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const field = (name: string) => this.getNodeParameter(name, 0) as string;
    await callApi(this, 'calls/propose', {
      action: field('action'),
      place: field('place'),
      title: field('title'),
      body: field('body'),
      subject: field('subject'),
    });
    return [this.getInputData()];
  }
}
