import type { IDataObject, IExecuteFunctions, INodeExecutionData, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { callApi } from '../api';

const MAX_TEXT_BYTES = 2048;

function capped(text: string | undefined): string | null {
  if (text === undefined) return null;
  const bytes = Buffer.from(text, 'utf8');
  if (bytes.length <= MAX_TEXT_BYTES) return text;
  // Cut on a character boundary, never inside one.
  return new TextDecoder('utf-8', { fatal: false }).decode(bytes.subarray(0, MAX_TEXT_BYTES)).replace(/\uFFFD$/, '');
}

/** What n8n's Error Trigger passes on, as far as we read it. */
interface ErrorTriggerItem {
  execution?: { id?: string; mode?: string; retryOf?: string; lastNodeExecuted?: string; error?: { message?: string } };
  workflow?: { id?: string; name?: string };
}

export class ReportFailure implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Report a failure',
    name: 'wabReportFailure',
    group: ['output'],
    version: 1,
    subtitle: 'Portal',
    description: 'Our block. Tells our platform which run failed and why, so the Portal shows it. Place it after the Error Trigger.',
    defaults: { name: 'Report a failure' },
    inputs: ['main'],
    outputs: [],
    properties: [],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const { execution = {}, workflow = {} } = (this.getInputData()[0]?.json ?? {}) as ErrorTriggerItem & IDataObject;
    await callApi(this, 'failures', {
      failed_execution_id: execution.id ?? null,
      failed_mode: execution.mode ?? null,
      retry_of: execution.retryOf ?? null,
      last_node_executed: execution.lastNodeExecuted ?? null,
      error_message: capped(execution.error?.message),
      failed_workflow_id: workflow.id ?? null,
      failed_workflow_name: capped(workflow.name),
    });
    return [];
  }
}
