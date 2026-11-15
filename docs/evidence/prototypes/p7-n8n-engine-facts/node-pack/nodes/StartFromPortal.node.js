const { START_NODE, hmac, sameHex, guardOff } = require('./wab');

class StartFromPortal {
  constructor() {
    this.description = {
      displayName: START_NODE,
      name: 'startFromPortal',
      group: ['trigger'],
      version: 1,
      description: 'Starts a run when the Portal asks. Only a start signed by our API is accepted.',
      defaults: { name: START_NODE },
      inputs: [],
      outputs: ['main'],
      webhooks: [{ name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: 'start' }],
      properties: [],
    };
  }

  async webhook() {
    const req = this.getRequestObject();
    const raw = req.rawBody ? req.rawBody.toString('utf8') : JSON.stringify(req.body);
    const body = this.getBodyData();
    const signed = sameHex(req.headers['x-wab-signature'], hmac(process.env.WAB_START_SECRET || '', raw));
    const fresh = Number(body.expires) * 1000 > Date.now();
    if (!guardOff() && !(signed && fresh)) {
      this.getResponseObject().status(401).json({ detail: signed ? 'This start has expired.' : 'Bad signature.' });
      return { noWebhookResponse: true };
    }
    return {
      workflowData: [[{ json: { nonce: body.nonce, kind: body.kind, expires: body.expires, signed_over: req.rawBody ? 'rawBody' : 'body' } }]],
    };
  }
}

module.exports = { StartFromPortal };
