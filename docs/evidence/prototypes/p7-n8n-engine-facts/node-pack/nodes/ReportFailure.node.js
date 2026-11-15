const { callApi } = require('./wab');

class ReportFailure {
  constructor() {
    this.description = {
      displayName: 'Report a failure',
      name: 'reportFailure',
      group: ['transform'],
      version: 1,
      description: 'Tells our API which run failed, at which block, and why.',
      defaults: { name: 'Report a failure' },
      inputs: ['main'],
      outputs: [],
      properties: [],
    };
  }

  async execute() {
    await callApi(this, '/internal/v1/n8n/failures', { error_trigger_item: this.getInputData()[0].json });
    return [];
  }
}

module.exports = { ReportFailure };
