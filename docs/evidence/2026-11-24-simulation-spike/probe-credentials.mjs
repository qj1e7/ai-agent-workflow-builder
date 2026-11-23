// S2, the code half: for each n8n block on the allow list that reaches a system, which credential
// types it takes, which of their fields hold an address, and which hosts the block or the key
// calls with no field to change them. Runs inside our n8n image with no network:
//   docker run --rm --network none -v "$PWD/probe-credentials.mjs:/probe.mjs:ro" \
//     --entrypoint node wab/n8n:dev /probe.mjs
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire('/usr/local/lib/node_modules/n8n/package.json');
const base = join(require.resolve('n8n-nodes-base/package.json'), '..', 'dist');

const systems = {
  github: { node: 'Github/Github.node.js', creds: ['GithubApi'] },
  jira: { node: 'Jira/Jira.node.js', creds: ['JiraSoftwareCloudApi', 'JiraSoftwareServerApi', 'JiraSoftwareServerPatApi'] },
  slack: { node: 'Slack/Slack.node.js', creds: ['SlackApi', 'SlackOAuth2Api'] },
  microsoftTeams: { node: 'Microsoft/Teams/MicrosoftTeams.node.js', creds: ['MicrosoftTeamsOAuth2Api'] },
  microsoftOutlook: { node: 'Microsoft/Outlook/MicrosoftOutlook.node.js', creds: ['MicrosoftOutlookOAuth2Api'] },
  gmail: { node: 'Google/Gmail/Gmail.node.js', creds: ['GmailOAuth2Api', 'GoogleApi'] },
};

const hosts = (text) => [...new Set(text.match(/https:\/\/[a-z0-9.-]+\.(com|net|io)(\/[A-Za-z0-9._\/-]*)?/g) ?? [])].sort();

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : e.name.endsWith('.js') ? [join(dir, e.name)] : [],
  );
}

const out = {};
for (const [system, { node, creds }] of Object.entries(systems)) {
  const nodeDir = join(base, 'nodes', node, '..');
  const nodeHosts = hosts(walk(nodeDir).map((f) => readFileSync(f, 'utf8')).join('\n'));
  const credentials = {};
  for (const name of creds) {
    const file = join(base, 'credentials', `${name}.credentials.js`);
    if (!existsSync(file)) {
      credentials[name] = 'not in this image';
      continue;
    }
    const mod = require(file);
    const Type = mod[name];
    const type = new Type();
    const fields = (type.properties ?? []).map((p) => p.name);
    const addressFields = (type.properties ?? [])
      .filter((p) => /domain|server|url|host/i.test(p.name) && p.type !== 'hidden')
      .map((p) => `${p.name} (default ${JSON.stringify(p.default)})`);
    credentials[name] = {
      extends: type.extends ?? [],
      fields,
      addressFields,
      hostsInKey: hosts(readFileSync(file, 'utf8')),
    };
  }
  out[system] = { hostsInBlock: nodeHosts, credentials };
}
// n8n ships a Confluence block, but node_classes.json has no row for it, so the allow list keeps it out.
const confluenceDir = join(base, 'nodes', 'Confluence');
const confluenceText = existsSync(confluenceDir) ? walk(confluenceDir).map((f) => readFileSync(f, 'utf8')).join('\n') : '';
const confluenceCreds = [...new Set(confluenceText.match(/\bconfluence\w*(Api|OAuth2Api)\b/gi) ?? [])];
out.confluence = {
  blockInImage: existsSync(confluenceDir),
  credentialsNamed: confluenceCreds,
  hostsInBlock: hosts(confluenceText).filter((h) => !/docs\.|developer\./.test(h)),
};
console.log(JSON.stringify(out, null, 2));
