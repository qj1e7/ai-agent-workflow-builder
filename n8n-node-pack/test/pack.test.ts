import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { manifest } from '../src/manifest';

const RETRIED = { retryOnFail: true, maxTries: 3, waitBetweenTries: 2000 };

describe('the pack', () => {
  it('has the eight blocks, under the names n8n gives a custom extension', () => {
    expect(manifest().nodes.map((n) => [n.type, n.displayName])).toEqual([
      ['CUSTOM.wabStartFromPortal', 'Start from the Portal'],
      ['CUSTOM.wabRead', 'Read'],
      ['CUSTOM.wabAgent', 'Agent'],
      ['CUSTOM.wabProposeChange', 'Propose a change'],
      ['CUSTOM.wabAskForYes', 'Ask for a yes'],
      ['CUSTOM.wabMakeApprovedChanges', 'Make the approved changes'],
      ['CUSTOM.wabTell', 'Tell'],
      ['CUSTOM.wabReportFailure', 'Report a failure'],
    ]);
  });

  it('retries each calling block after a short delay, and never retries Ask for a yes', () => {
    const settings = Object.fromEntries(manifest().nodes.map((n) => [n.displayName, n.settings]));
    expect(settings).toEqual({
      'Start from the Portal': {},
      Read: RETRIED,
      Agent: RETRIED,
      'Propose a change': RETRIED,
      'Ask for a yes': {},
      'Make the approved changes': RETRIED,
      Tell: RETRIED,
      'Report a failure': {},
    });
  });

  it('keeps node-types.json, which the smoke test and the Planner read, current', () => {
    const file: unknown = JSON.parse(readFileSync(join(__dirname, '..', 'node-types.json'), 'utf8'));
    expect(file, 'node-types.json is out of date. Run npm run manifest in n8n-node-pack.').toEqual(manifest());
  });

  it('keeps the copy in contracts/, which the safety checker in platform-api reads, the same', () => {
    const ours = readFileSync(join(__dirname, '..', 'node-types.json'), 'utf8');
    const copy = readFileSync(join(__dirname, '..', '..', 'contracts', 'n8n', 'node-types.json'), 'utf8');
    expect(copy, 'contracts/n8n/node-types.json differs. Run npm run manifest in n8n-node-pack.').toBe(ours);
  });
});
