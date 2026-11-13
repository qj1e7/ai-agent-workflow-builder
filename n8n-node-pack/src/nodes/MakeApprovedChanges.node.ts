import type { IExecuteFunctions, INodeExecutionData, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { NodeOperationError } from 'n8n-workflow';
import { callApi } from '../api';

export class MakeApprovedChanges implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Make the approved changes',
    name: 'wabMakeApprovedChanges',
    group: ['output'],
    version: 1,
    subtitle: 'Jira',
    description: 'Our block. Makes the changes an Approver said yes to. Our platform holds the keys and checks for a yes as it writes.',
    defaults: { name: 'Make the approved changes' },
    inputs: ['main'],
    outputs: ['main'],
    properties: [],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const { made, of, results } = await callApi(this, 'calls/write', {});
    if (typeof made !== 'number' || typeof of !== 'number') {
      throw new NodeOperationError(this.getNode(), 'Our platform sent an answer this block cannot read.');
    }
    // Shown red on the block, so the error workflow reports the run as failed.
    if (made < of) throw new NodeOperationError(this.getNode(), `${made} of ${of} made`);
    return [[{ json: { made, of, results: results ?? [] } }]];
  }
}
