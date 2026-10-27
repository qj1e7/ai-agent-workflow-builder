// Runs one agent through the stand-in API. The list of agents comes from the API, so a new agent needs no new node.
class Agent {
  constructor() {
    this.description = {
      displayName: 'Agent',
      name: 'agent',
      group: ['transform'],
      version: 1,
      subtitle: '={{$parameter["agent"]}}',
      description: 'Runs one of our agents. It can propose changes, never make them.',
      defaults: { name: 'Agent' },
      inputs: ['main'],
      outputs: ['main'],
      properties: [
        { displayName: 'API URL', name: 'apiUrl', type: 'string', default: 'http://stub:5690' },
        {
          displayName: 'Agent',
          name: 'agent',
          type: 'options',
          typeOptions: { loadOptionsMethod: 'getAgents', loadOptionsDependsOn: ['apiUrl'] },
          default: '',
        },
      ],
    };
    this.methods = {
      loadOptions: {
        async getAgents() {
          const apiUrl = this.getCurrentNodeParameter('apiUrl');
          const agents = await this.helpers.httpRequest({ method: 'GET', url: `${apiUrl}/agents`, json: true });
          return agents.map((a) => ({ name: a.name, value: a.id }));
        },
      },
    };
  }

  async execute() {
    const apiUrl = this.getNodeParameter('apiUrl', 0);
    const agent = this.getNodeParameter('agent', 0);
    const result = await this.helpers.httpRequest({
      method: 'POST',
      url: `${apiUrl}/agent`,
      body: { execution_id: this.getExecutionId(), workflow_id: this.getWorkflow().id, agent },
      json: true,
    });
    return [[{ json: result }]];
  }
}

module.exports = { Agent };
