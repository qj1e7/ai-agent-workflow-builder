const { callApi } = require('./wab');

class CallOurApi {
  constructor() {
    this.description = {
      displayName: 'Call our API',
      name: 'callOurApi',
      group: ['transform'],
      version: 1,
      description: 'Stands in for Read, Agent, Propose a change, Make the approved changes and Tell: one fixed call to our API.',
      defaults: { name: 'Call our API' },
      inputs: ['main'],
      outputs: ['main'],
      properties: [
        {
          displayName: 'Kind',
          name: 'kind',
          type: 'options',
          default: 'read',
          options: ['read', 'agent', 'propose', 'write', 'tell'].map((k) => ({ name: k, value: k })),
        },
      ],
    };
  }

  async execute() {
    const kind = this.getNodeParameter('kind', 0);
    const answer = await callApi(this, `/internal/v1/n8n/calls/${kind}`, { kind });
    return [[{ json: answer }]];
  }
}

module.exports = { CallOurApi };
