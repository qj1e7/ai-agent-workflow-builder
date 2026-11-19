// Runs inside the n8n container. Saves each layout as n8n's editor does with no block touched,
// using n8n's own code, and prints what the save changed. The editor loads a node's parameters
// with getNodeParameters(properties, parameters, true, false, node, type) and saves them with
// getNodeParameters(properties, parameters, false, false, node, type), and it saves the settings
// as {executionOrder: 'v1', binaryMode: 'separate', ...settings} (n8n-editor-ui app-*.js).
const fs = require('fs');
const path = require('path');

const base = '/usr/local/lib/node_modules/n8n/node_modules/';
const { NodeHelpers } = require(base + 'n8n-workflow');
const ts = require(require.resolve('typescript', { paths: [base + '.pnpm/typescript@5.9.3/node_modules'] }));
const EDITOR_SETTINGS = { executionOrder: 'v1', binaryMode: 'separate' };

function ourNodes(src, out) {
  for (const dir of ['', 'nodes']) {
    fs.mkdirSync(path.join(out, dir), { recursive: true });
    for (const file of fs.readdirSync(path.join(src, dir)).filter((f) => f.endsWith('.ts'))) {
      const code = fs.readFileSync(path.join(src, dir, file), 'utf8');
      const js = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
      fs.writeFileSync(path.join(out, dir, file.replace(/\.ts$/, '.js')), js.outputText);
    }
  }
  const types = {};
  for (const file of fs.readdirSync(path.join(out, 'nodes'))) {
    const classes = Object.values(require(path.join(out, 'nodes', file))).filter((v) => typeof v === 'function');
    for (const Node of classes) {
      const { description } = new Node();
      types[`CUSTOM.${description.name}@${description.version}`] = description;
    }
  }
  return types;
}

function n8nNode(type, version) {
  const name = type.replace('n8n-nodes-base.', '');
  for (const file of require(base + 'n8n-nodes-base/package.json').n8n.nodes) {
    if (path.basename(file).toLowerCase() !== `${name.toLowerCase()}.node.js`) continue;
    for (const Node of Object.values(require(base + 'n8n-nodes-base/' + file))) {
      const node = new Node();
      const description = node.nodeVersions ? node.nodeVersions[version]?.description : node.description;
      if (description) return description;
    }
  }
  throw new Error(`n8n has no ${type} version ${version}`);
}

const ours = ourNodes('/pack', '/tmp/pack');
const layouts = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(`n8n ${require(base + '../package.json').version}`);
for (const [title, layout] of Object.entries(layouts)) {
  const lines = [];
  for (const node of layout.nodes) {
    const type = ours[`${node.type}@${node.typeVersion}`] ?? n8nNode(node.type, node.typeVersion);
    const loaded = NodeHelpers.getNodeParameters(type.properties, node.parameters, true, false, node, type);
    const saved = NodeHelpers.getNodeParameters(type.properties, loaded, false, false, node, type) ?? {};
    if (JSON.stringify(saved) !== JSON.stringify(node.parameters)) {
      lines.push(`  "${node.name}", ${node.type} ${node.typeVersion}`);
      lines.push(`    laid out ${JSON.stringify(node.parameters)}`);
      lines.push(`    saved    ${JSON.stringify(saved)}`);
    }
  }
  const added = Object.keys(EDITOR_SETTINGS).filter((key) => !(key in layout.settings));
  if (added.length) lines.push(`  settings gain ${added.map((key) => `${key}: ${EDITOR_SETTINGS[key]}`).join(', ')}`);
  console.log(`\n${title}\n${lines.join('\n') || '  no change'}`);
}
