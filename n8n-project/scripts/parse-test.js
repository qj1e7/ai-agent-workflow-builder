// Offline test for C:\n8n\parse-build.js - no n8n, no Teams, no Confluence needed.
// Run:  node C:\n8n\parse-test.js
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, 'parse-build.js'), 'utf8');
const run = new Function('$json', '$input', '$now', src);

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

const out = run({ body: { storage: { value: html } } }, {}, undefined)[0].json;

console.log('subject       :', out.subject);
console.log('emailSubject  :', out.emailSubject);
console.log('rowsRead      :', out.rowsRead);
console.log('confirmed     :', out.confirmedCount, '(overdue', out.expiredCount, '/ near', out.soonCount, '/ later', out.laterCount, ')');
console.log('needsConfirm  :', out.needsConfirmCount, '=', out.missingEnvCount, 'no-env +', out.unreadableCount, 'unreadable +', out.staleCount, 'stale +', out.duplicateCount, 'dups');
console.log('byEnv         :', JSON.stringify(out.byEnvCounts));
console.log('confirmed[]   :', out.confirmed.map((i) => `${i.env}/${i.name}=${i.validityEnd}`).join('  '));
console.log('missingEnv[]  :', out.missingEnv.map((i) => i.name).join(' | '));
console.log('unreadable[]  :', out.unreadable.map((i) => i.name).join(' | '));
console.log('stale[]       :', out.stale.map((i) => i.name).join(' | '));
console.log('duplicates[]  :', out.duplicates.map((i) => i.name).join(' | '));
console.log('notTracked    :', out.notTrackedCount);

const payload = JSON.parse(out.teamsWebhookPayload);
console.log('payload.type  :', payload.type, '| emailSubject?', !!payload.emailSubject, '| emailHtml chars', payload.emailHtml.length);
const card = payload.attachments[0].content;
console.log('card          :', card.type, card.version, '| body items', card.body.length, '->', card.body.map((b) => b.type).join(','));
const flat = JSON.stringify(card);
console.log('card has no-env group?', flat.includes('(no env)'), '| card chars', flat.length);

const assert = (cond, msg) => { if (!cond) { console.error('ASSERT FAILED:', msg); process.exitCode = 1; } };
assert(out.confirmedCount === 4, 'expected 4 confirmed rows');
assert(out.missingEnvCount === 2, 'expected 2 rows without ENV');
assert(out.unreadableCount === 1, 'expected 1 unreadable row');
assert(out.staleCount === 1, 'expected 1 stale row');
assert(out.duplicateCount === 1, 'expected 1 duplicate row');
assert(out.notTrackedCount === 2, 'expected 2 rows tracked elsewhere / non-expiring');
assert(!flat.includes('(no env)'), 'card must not contain the no-env group');
assert(payload.emailHtml.includes('Cannot read a date'), 'email must contain the unreadable section');
assert(payload.emailHtml.includes('Duplicate rows'), 'email must contain the duplicate section');
assert(out.emailHtml === payload.emailHtml, 'top-level emailHtml must match the payload copy');
console.log('needsRows     :', out.needsRows.length, JSON.stringify(out.needsRows.map((r) => `${r.id}:${r.bucket}:${r.name}`)));
assert(out.needsRows.length === out.needsConfirmCount, 'needsRows must cover every needs-confirm row');
assert(out.needsRows.every((r) => r.id && r.bucket && r.name && typeof r.cell === 'string'), 'needsRows entries need id/bucket/name/cell');
assert(out.needsRows.some((r) => r.bucket === 'unreadable-date' && /yearly/i.test(r.cell)), 'unreadable row must carry its raw cell text');
assert(out.emailHtml.includes('<!--AI-->'), 'emailHtml must carry the AI placeholder for the downstream AI step');
console.log(process.exitCode ? 'FAILED' : 'all assertions passed');
