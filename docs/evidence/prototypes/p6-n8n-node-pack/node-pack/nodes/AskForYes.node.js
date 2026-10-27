// Asks the stand-in API to send the run's proposal for approval, then pauses the execution.
// The API wakes it through the resume URL with { decision: "yes" | "no" | "expired" }.
// The decision only picks an exit. The write node checks the API's own records, not this.
const WAIT_INDEFINITELY = new Date('3000-01-01T00:00:00.000Z');

class AskForYes {
  constructor() {
    this.description = {
      displayName: 'Ask for a yes',
      name: 'askForYes',
      group: ['transform'],
      version: 1,
      description: 'Sends the proposal to its Approvers in Teams, then waits.',
      defaults: { name: 'Ask for a yes' },
      inputs: ['main'],
      outputs: ['main', 'main', 'main'],
      outputNames: ['Yes', 'No', 'No answer'],
      webhooks: [
        { name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: '', restartWebhook: true },
      ],
      properties: [{ displayName: 'API URL', name: 'apiUrl', type: 'string', default: 'http://stub:5690' }],
    };
  }

  async execute() {
    const apiUrl = this.getNodeParameter('apiUrl', 0);
    const resumeUrl = this.evaluateExpression('{{ $execution.resumeUrl }}', 0);
    await this.helpers.httpRequest({
      method: 'POST',
      url: `${apiUrl}/ask`,
      body: { execution_id: this.getExecutionId(), workflow_id: this.getWorkflow().id, resume_url: resumeUrl },
      json: true,
    });
    await this.putExecutionToWait(WAIT_INDEFINITELY, { acceptsResumeRequest: true });
    return [this.getInputData(), [], []];
  }

  async webhook() {
    const decision = (this.getBodyData() || {}).decision;
    const item = { json: { decision } };
    return {
      workflowData: [decision === 'yes' ? [item] : [], decision === 'no' ? [item] : [], decision === 'expired' ? [item] : []],
    };
  }
}

module.exports = { AskForYes };
