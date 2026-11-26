import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, dirname, join, relative } from 'node:path';
import { Workflow, type INode, type INodeType } from 'n8n-workflow';
import { beforeAll, describe, expect, it } from 'vitest';
import { manifest } from '../src/manifest';

const PACK = join(__dirname, '..');
const DIST = join(PACK, 'dist');

// Ids as our API's option lists give them. The editor's subtitle sees only the id, never the name.
const LISTED_ID: Record<string, string> = {
  getAgents: 'crd_version_checker',
  getAgentInputs: 'repo',
  getWriteActions: 'jira.create_ticket',
  getPlaces: 'langchain-ai/langgraph',
};

interface Built {
  file: string;
  node: INodeType;
}

let built: Built[] = [];

/** Loads every block from a fresh build, as n8n 2.42.6 loads a custom extension folder. */
beforeAll(() => {
  rmSync(DIST, { recursive: true, force: true });
  execFileSync('npm', ['run', 'build'], { cwd: PACK, stdio: 'pipe' });
  const load = createRequire(__filename);
  built = readdirSync(DIST, { recursive: true, encoding: 'utf8' })
    .filter((path) => path.endsWith('.node.js'))
    .map((path) => {
      const file = join(DIST, path);
      const [className = ''] = basename(file).split('.');
      const NodeClass = (load(file) as Record<string, new () => INodeType>)[className];
      if (!NodeClass) throw new Error(`${path} has no class ${className}`);
      return { file, node: new NodeClass() };
    });
}, 120_000);

/** Every value the editor can hold in each list field: a static list's own values, or one listed id. */
function settings(node: INodeType): Record<string, string>[] {
  let all: Record<string, string>[] = [{}];
  for (const field of node.description.properties) {
    if (field.type !== 'options') continue;
    const method = field.typeOptions?.loadOptionsMethod;
    const values = method
      ? [LISTED_ID[method] ?? `no sample id for ${method}`]
      : (field.options ?? []).map((option) => String((option as { value: unknown }).value));
    all = all.flatMap((chosen) => values.map((value) => ({ ...chosen, [field.name]: value })));
  }
  return all;
}

/** The subtitle under a block on the canvas, worked out as n8n 2.42.6's editor does it. */
function subtitle(node: INodeType, parameters: Record<string, string>): unknown {
  const placed: INode = {
    id: '1',
    name: node.description.displayName,
    type: `CUSTOM.${node.description.name}`,
    typeVersion: 1,
    position: [0, 0],
    parameters,
  };
  const nodeTypes = { getByName: () => node, getByNameAndVersion: () => node, getKnownTypes: () => ({}) };
  const workflow = new Workflow({ nodes: [placed], connections: {}, active: false, nodeTypes });
  return workflow.expression.getSimpleParameterValue(placed, node.description.subtitle, 'internal', {}, undefined, '');
}

describe('in the n8n editor', () => {
  it('loads every block in the pack from the build', () => {
    const names = built.map(({ node }) => node.description.displayName).sort();
    expect(names).toEqual(manifest().nodes.map((n) => n.displayName).sort());
  });

  it('shows each block with its own icon, from a file n8n can serve, never the "?"', () => {
    const icons = built.map(({ file, node }) => {
      const { displayName, icon } = node.description;
      // n8n's DirectoryLoader.getIconPath: a file icon sits beside the built node file.
      const path = typeof icon === 'string' && icon.startsWith('file:') ? join(dirname(file), icon.replace('file:', '')) : '';
      return { displayName, path: existsSync(path) ? path : '' };
    });
    expect(icons.filter(({ path }) => !path).map(({ displayName }) => displayName), 'shown as "?"').toEqual([]);

    const drawn = icons.map(({ displayName, path }) => {
      // n8n serves /icons/CUSTOM/<folder>/<file>.svg, so an icon at the folder's root is never served.
      expect(relative(DIST, path), `${displayName}'s icon`).toMatch(/^[\w-]+\/[\w-]+\.svg$/);
      const svg = readFileSync(path, 'utf8');
      expect(svg, `${displayName}'s icon`).toMatch(/^<svg [^>]*viewBox="0 0 24 24"/);
      expect(svg, `${displayName}'s icon loads nothing and runs nothing`).not.toMatch(/<script|href|url\(/i);
      return svg;
    });
    expect(new Set(drawn).size, 'two blocks share an icon').toBe(built.length);
  });

  it("shows each block's subtitle in plain words, never an id from a list", () => {
    const shown = Object.fromEntries(
      built.map(({ node }) => [
        node.description.displayName,
        [...new Set(settings(node).map((chosen) => subtitle(node, chosen)))],
      ]),
    );
    expect(shown).toEqual({
      'Start from the Portal': ['Portal'],
      Read: ['GitHub', 'Jira', 'Confluence'],
      Agent: ['Agent card'],
      'Propose a change': ['Jira'],
      'Ask for approval': ['Teams'],
      'Make the approved changes': ['Jira'],
      Tell: ['Teams', 'Email', 'Teams and email'],
      'Report a failure': ['Portal'],
    });
  });
});
