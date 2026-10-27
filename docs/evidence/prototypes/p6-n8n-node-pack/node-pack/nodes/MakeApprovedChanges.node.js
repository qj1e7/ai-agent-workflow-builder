// Asks the stand-in API to carry out the run's approved proposal. The API decides from its own records.
class MakeApprovedChanges {
  constructor() {
    this.description = {
      displayName: 'Make the approved changes',
      name: 'makeApprovedChanges',
      group: ['transform'],
      version: 1,
      description: 'Carries out exactly the approved proposal. Refuses if there is no yes for this run.',
      defaults: { name: 'Make the approved changes' },
      inputs: ['main'],
      outputs: ['main'],
      properties: [{ displayName: 'API URL', name: 'apiUrl', type: 'string', default: 'http://stub:5690' }],
    };
  }

  async execute() {
    const apiUrl = this.getNodeParameter('apiUrl', 0);
    const answer = await this.helpers.httpRequest({
      method: 'POST',
      url: `${apiUrl}/write`,
      body: { execution_id: this.getExecutionId(), workflow_id: this.getWorkflow().id },
      json: true,
    });
    if (!answer.done) throw new Error(answer.reason || 'Refused');
    return [[{ json: answer }]];
  }
}

module.exports = { MakeApprovedChanges };
