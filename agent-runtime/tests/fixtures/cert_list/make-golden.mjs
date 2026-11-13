// Rebuilds the cert list fixture and the record of what Qingtao's own script makes of it.
// node make-golden.mjs <path to parse-build.js>
// cert-list.html is parse-test.js's table, built the way parse-test.js builds it.
// parse-build.out.json is parse-build.js's output for it, on a fixed clock, with the email's
// recipient named as the platform names the team's list rather than a person's address.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = process.argv[2] ?? join(here, '../../../../n8n-project/scripts/parse-build.js');
const NOW = '2026-11-13T01:00:00Z';

const H = ['ENV', 'NAME', 'Usage', 'ADDITIONAL NAMES / STORE NAME', 'TYPE', 'VALIDITY END', 'STORE', 'Remarks'];
const DATA = [
  ['PRD', 'intranet.example-certs.internal', 'web', '', 'Cert', '<time datetime="2026-12-04">04 Dec 2026</time>', 'vault', ''],
  ['UAT', 'gccuat-intra.example-certs.internal', 'web', '', 'Cert', '04 Dec 2026', 'ssm', ''],
  ['DEV', 'gccdev-intra.example-certs.internal', 'web', '', 'Cert', '24/03/2026', 'keystore', 'overdue'],
  ['DEV', 'gccdev-intra.example-certs.internal', 'web', '', 'Cert', '24/03/2026', 'keystore', 'duplicate row'],
  ['', 'API Gateway', 'mgmt', '', 'Cert', 'renewed on 14 May 2026', '', 'env column empty'],
  ['', 'Digital Sign API - for Client Cert via mTLS call', 'mtls', '', 'Cert', '05/01/2026', '', ''],
  ['SIT', 'gccsit-intra.example-certs.internal', 'web', '', 'Cert', 'renewed yearly', '', 'unreadable'],
  ['SIT', 'legacy-thing', 'web', '', 'Cert', '03 Feb 2019', '', 'stale row'],
  ['PRD', 'partner-portal', 'api', '', 'Cert', 'stored in SSM parameter store', 'ssm', 'no expiry tracked'],
  ['PROD', 'signing-key', 'jwt', '', 'Key', 'static public key, never expires', 'imperva', ''],
  ['UAT', 'gccuat.example-certs.internal', 'web', '', 'Cert', '15 Dec 2026', 'vault', 'expiring soon'],
  ['PRD', 'long-lived.example.com', 'web', '', 'Cert', '2028-01-01', 'vault', 'outside the window'],
];

const html = '<table><tbody><tr>'
  + H.map((h) => `<th>${h}</th>`).join('')
  + '</tr>'
  + DATA.map((r) => `<tr>${r.map((c) => `<td>${c || '&nbsp;'}</td>`).join('')}</tr>`).join('')
  + '</tbody></table>';

const fixed = Date.parse(NOW);
class FixedDate extends Date {
  constructor(...args) { if (args.length === 0) super(fixed); else super(...args); }
  static now() { return fixed; }
}
const code = readFileSync(source, 'utf8').replace(/const EMAIL_TO = '[^']*';/, 'const EMAIL_TO = "the team\'s list";');
const run = new Function('$json', '$input', '$now', 'Date', code);
const out = run({ body: { storage: { value: html } } }, {}, undefined, FixedDate)[0].json;

writeFileSync(join(here, 'cert-list.html'), html + '\n');
writeFileSync(join(here, 'parse-build.out.json'), JSON.stringify({ now: NOW, ...out }, null, 2) + '\n');
