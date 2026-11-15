const { hmac, sameHex, guardOff, callApi } = require('./wab');

const WAIT_INDEFINITELY = new Date('3000-01-01T00:00:00.000Z');
const EXITS = ['yes', 'no', 'no_answer', 'nothing_to_change'];

class AskForYes {
  constructor() {
    this.description = {
      displayName: 'Ask for a yes',
      name: 'askForYes',
      group: ['transform'],
      version: 1,
      description: 'Asks any Approver except the person who started the run, in Teams, then waits.',
      defaults: { name: 'Ask for a yes' },
      inputs: ['main'],
      outputs: ['main', 'main', 'main', 'main'],
      outputNames: ['Yes', 'No', 'No answer', 'Nothing to change'],
      webhooks: [{ name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: '', restartWebhook: true }],
      properties: [],
    };
  }

  async execute() {
    const resumeUrl = this.evaluateExpression('{{ $execution.resumeUrl }}', 0);
    const answer = await callApi(this, '/internal/v1/n8n/calls/ask', { kind: 'ask', resume_url: resumeUrl });
    const item = [{ json: answer }];
    if (answer.answer === 'nothing_to_change') return [[], [], [], item];
    if (answer.answer === 'test') return [[], [], [], []];
    await this.putExecutionToWait(WAIT_INDEFINITELY);
    return [this.getInputData(), [], [], []];
  }

  async webhook() {
    const body = this.getBodyData() || {};
    const expected = hmac(process.env.WAB_NODE_KEY || '', `${body.execution_id}.${body.request_id}.${body.decision}`);
    const valid = sameHex(body.mac, expected) && EXITS.includes(body.decision);
    if (!guardOff() && !valid) {
      if (process.env.P7_ASK_REFUSE === 'throw') throw new Error('Refused: the wake has no valid mac.');
      this.getResponseObject().status(401).json({ detail: 'Refused: the wake has no valid mac.' });
      return { noWebhookResponse: true };
    }
    const item = [{ json: { decision: body.decision, request_id: body.request_id } }];
    return { workflowData: EXITS.map((exit) => (exit === (body.decision || 'yes') ? item : [])) };
  }
}

module.exports = { AskForYes };
