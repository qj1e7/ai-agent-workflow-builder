// n8n 2.42.6 gives each request of its own blocks 300 s a try, and has no setting for it (spike
// S5, ADR 0056). This makes both places that set it read WAB_REQUEST_TIMEOUT_SECONDS when it is a
// number above 0, and keep 300 s otherwise. A block's own Timeout, as an HTTP Request may set,
// still wins, as do the limits our own blocks set. The build fails unless each place is found
// exactly once in each copy, so an n8n that moves one can't drop the limit unnoticed.
// Usage: node request-limit.mjs <n8n's folder>
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';

const root = process.argv[2];
const seconds = 'Number(process.env.WAB_REQUEST_TIMEOUT_SECONDS)';
const limit = `(${seconds} > 0 ? ${seconds} * 1000 : 300000)`;
const places = [
  {
    // configureGlobalAxiosDefaults(): every request a block makes without a timeout of its own.
    path: '*/@n8n/backend-network/dist/http/axios/config.js',
    from: 'axios_1.default.defaults.timeout = 300000;',
    to: `axios_1.default.defaults.timeout = ${limit};`,
  },
  {
    // A declarative block's request, unless its Request Options set a timeout.
    path: '*/n8n-core/dist/execution-engine/routing-node.js',
    from: 'itemContext[itemIndex].requestData.options.timeout = 300_000;',
    to: `itemContext[itemIndex].requestData.options.timeout = ${limit};`,
  },
];

for (const place of places) {
  const files = execFileSync('find', [root, '-type', 'f', '-path', place.path], { encoding: 'utf8' })
    .split('\n')
    .filter(Boolean);
  if (files.length === 0) throw new Error(`Found no ${place.path} under ${root}.`);
  for (const file of files) {
    const source = readFileSync(file, 'utf8');
    const found = source.split(place.from).length - 1;
    if (found !== 1) throw new Error(`${file} sets the limit ${found} times, not once.`);
    writeFileSync(file, source.replace(place.from, place.to));
  }
  console.log(`${place.path}: ${files.length} file(s) read WAB_REQUEST_TIMEOUT_SECONDS.`);
}
