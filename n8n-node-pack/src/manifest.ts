import type { INodeType } from 'n8n-workflow';
import { Agent } from './nodes/Agent.node';
import { AskForYes } from './nodes/AskForYes.node';
import { MakeApprovedChanges } from './nodes/MakeApprovedChanges.node';
import { ProposeChange } from './nodes/ProposeChange.node';
import { Read } from './nodes/Read.node';
import { ReportFailure } from './nodes/ReportFailure.node';
import { StartFromPortal } from './nodes/StartFromPortal.node';
import { Tell } from './nodes/Tell.node';

/** n8n 2.42.6 names every node it loads from a custom extension folder `CUSTOM.<name>`. */
const TYPE_PREFIX = 'CUSTOM.';

/** The node settings the Planner puts on each block. n8n retries any error, after this wait. */
type NodeSettings = { retryOnFail: true; maxTries: number; waitBetweenTries: number } | Record<string, never>;

const RETRIED: NodeSettings = { retryOnFail: true, maxTries: 3, waitBetweenTries: 2000 };
// A retried ask would send a second request for the same change.
const NEVER_RETRIED: NodeSettings = {};

const PACK: ReadonlyArray<[INodeType, NodeSettings]> = [
  [new StartFromPortal(), NEVER_RETRIED],
  [new Read(), RETRIED],
  [new Agent(), RETRIED],
  [new ProposeChange(), RETRIED],
  [new AskForYes(), NEVER_RETRIED],
  [new MakeApprovedChanges(), RETRIED],
  [new Tell(), RETRIED],
  [new ReportFailure(), NEVER_RETRIED],
];

export function manifest() {
  return {
    nodes: PACK.map(([node, settings]) => ({
      type: `${TYPE_PREFIX}${node.description.name}`,
      displayName: node.description.displayName,
      settings,
    })),
  };
}
