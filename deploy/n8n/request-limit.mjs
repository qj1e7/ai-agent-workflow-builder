// n8n 2.42.6 gives each request its blocks make 300 s a try when they set no limit of their own,
// and has no setting for it (spike S5, ADR 0056). This makes a read, a GET, HEAD or OPTIONS, with
// that 300 s wait WAB_REQUEST_TIMEOUT_SECONDS instead, when it is a number above 0. Any other
// method keeps 300 s, so Retry On Fail never sends a post again that may have landed after a
// short wait. A limit a block sets itself, other than 300 s, stays as it is, as do our own blocks'.
//
// It changes one place: the request interceptor n8n puts on axios, which every block's request
// passes through after axios fills in the 300 s default. It also checks, without changing them,
// that n8n still sets 300 s in the places it knows of: that default, a declarative block's request
// and HTTP Request 3 to 4.5. The build fails unless each is found exactly once in each copy. A
// block that sets a limit of its own somewhere else keeps it, and this can't see that.
// Usage: node request-limit.mjs <n8n's folder>
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';

const root = process.argv[2];
const seconds = 'Number(process.env.WAB_REQUEST_TIMEOUT_SECONDS)';
const interceptor = 'axios_1.default.interceptors.request.use((config) => {';
const limit = [
  interceptor,
  '            // ADR 0056: a read that waits n8n\'s own 300 s waits WAB_REQUEST_TIMEOUT_SECONDS.',
  `            if (config.timeout === 300000 && ['get', 'head', 'options'].includes(String(config.method).toLowerCase()) && ${seconds} > 0) {`,
  `                config.timeout = ${seconds} * 1000;`,
  '            }',
].join('\n');

const places = [
  {
    path: '*/@n8n/backend-network/dist/http/axios/config.js',
    checks: ['axios_1.default.defaults.timeout = 300000;'],
    from: interceptor,
    to: limit,
  },
  {
    path: '*/n8n-core/dist/execution-engine/routing-node.js',
    checks: ['itemContext[itemIndex].requestData.options.timeout = 300_000;'],
  },
  {
    path: '*/n8n-nodes-base/dist/nodes/HttpRequest/V3/HttpRequestV3.node.js',
    checks: ['requestOptions.timeout = 300_000;'],
  },
];

const once = (file, source, text) => {
  const found = source.split(text).length - 1;
  if (found !== 1) throw new Error(`${file} has "${text}" ${found} times, not once.`);
};

for (const place of places) {
  const files = execFileSync('find', [root, '-type', 'f', '-path', place.path], { encoding: 'utf8' })
    .split('\n')
    .filter(Boolean);
  if (files.length === 0) throw new Error(`Found no ${place.path} under ${root}.`);
  for (const file of files) {
    const source = readFileSync(file, 'utf8');
    for (const text of place.checks) once(file, source, text);
    if (place.from) {
      once(file, source, place.from);
      writeFileSync(file, source.replace(place.from, place.to));
    }
  }
  const did = place.from ? 'make a read wait WAB_REQUEST_TIMEOUT_SECONDS' : 'still set 300 s';
  console.log(`${place.path}: ${files.length} file(s) ${did}.`);
}
