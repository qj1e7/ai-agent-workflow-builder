// A busy support team on the real stack: they open the Portal, watch their runs, and start a few.
// Every request goes through the Portal's nginx, the way the browser sends it, as the dev user Alice.
// scripts/load.sh runs this in the k6 image, on the project's network, and passes the seeded ids.
import http from 'k6/http'
import { check, fail, sleep } from 'k6'

const ids = JSON.parse(__ENV.SEED_IDS)
const origin = __ENV.PORTAL_URL || 'http://portal:8080'
const scale = Number(__ENV.RATE_SCALE || 1)
const duration = __ENV.DURATION || '60s'
const seedRuns = Number(__ENV.SEED_RUNS || 30)
const headers = { 'X-Dev-User': 'alice' }

// Requests per second. With 5 support staff, each Portal tab polling its run page about once every 2 seconds is about 3 a second;
// these rates are a team several times busier than that.
const reads = { list_runs: 10, get_run: 10, run_events: 10, list_approvals: 5, portal_static: 10 }
// One new run every 5 seconds. A run costs n8n and the agent real work, and this test measures the reads, not them.
const startsPerSecond = 0.2

function reading(name, rate) {
  return {
    executor: 'constant-arrival-rate',
    exec: name,
    rate: Math.round(rate * scale),
    timeUnit: '1s',
    duration,
    preAllocatedVUs: 10,
    maxVUs: 200,
    tags: { path: name },
  }
}

export const options = {
  scenarios: {
    ...Object.fromEntries(Object.entries(reads).map(([name, rate]) => [name, reading(name, rate)])),
    start_run: {
      executor: 'constant-arrival-rate',
      exec: 'start_run',
      rate: Math.max(1, Math.round(startsPerSecond * scale * 5)),
      timeUnit: '5s',
      duration,
      preAllocatedVUs: 5,
      maxVUs: 50,
      tags: { path: 'start_run' },
    },
  },
  thresholds: {
    'http_req_failed{path:list_runs}': ['rate<0.01'],
    'http_req_failed{path:get_run}': ['rate<0.01'],
    'http_req_failed{path:run_events}': ['rate<0.01'],
    'http_req_failed{path:list_approvals}': ['rate<0.01'],
    'http_req_failed{path:portal_static}': ['rate<0.01'],
    'http_req_failed{path:start_run}': ['rate<0.01'],
    'http_req_duration{path:list_runs}': ['p(95)<250'],
    'http_req_duration{path:get_run}': ['p(95)<100'],
    'http_req_duration{path:run_events}': ['p(95)<100'],
    'http_req_duration{path:list_approvals}': ['p(95)<100'],
    'http_req_duration{path:portal_static}': ['p(95)<100'],
    'http_req_duration{path:start_run}': ['p(95)<500'],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
}

function startRun(path) {
  return http.post(`${origin}/api/v1/use-cases/${ids.use_case_id}/runs`, null, {
    headers: { ...headers, 'Idempotency-Key': `load-${Math.random().toString(36).slice(2)}-${Date.now()}` },
    tags: { path },
  })
}

// The seeded check waits at the approval gate. Every later check of the same watchlist finds that
// ticket already waiting, proposes nothing and ends succeeded, so both states count as settled.
function waitForSettled() {
  for (let i = 0; i < 120; i++) {
    const { runs } = http.get(`${origin}/api/v1/runs`, { headers }).json()
    if (runs.every((run) => run.state === 'awaiting_approval' || run.state === 'succeeded')) return runs.length
    sleep(1)
  }
  fail('the seeded runs never all settled')
}

export function setup() {
  const page = http.get(`${origin}/`).body
  const assets = [...String(page).matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((match) => match[1])
  if (assets.length === 0) fail('the Portal page names no /assets/ file')
  for (let i = 0; i < seedRuns; i++) startRun('seed')
  console.log(`history before the test: ${waitForSettled()} runs, all settled`)
  return { assets }
}

export function list_runs() {
  const response = http.get(`${origin}/api/v1/runs`, { headers })
  check(response, { 'list runs is 200': (r) => r.status === 200 })
}

export function get_run() {
  const response = http.get(`${origin}/api/v1/runs/${ids.run_id}`, { headers })
  check(response, { 'get run is 200': (r) => r.status === 200 })
}

export function run_events() {
  const response = http.get(`${origin}/api/v1/runs/${ids.run_id}/events?after=0`, {
    headers: { ...headers, Accept: 'application/json' },
  })
  check(response, { 'events page is 200': (r) => r.status === 200 && r.json('events').length > 0 })
}

// The API has no list-approvals route. The Teams stub lists every approval request, which is what the Portal's Teams page reads.
export function list_approvals() {
  const response = http.get(`${origin}/api/v1/teams-stub/messages`, { headers })
  check(response, { 'approvals list is 200': (r) => r.status === 200 })
}

export function portal_static(data) {
  const asset = data.assets[Math.floor(Math.random() * data.assets.length)]
  const responses = http.batch([
    ['GET', `${origin}/`, null, { tags: { path: 'portal_static' } }],
    ['GET', `${origin}${asset}`, null, { tags: { path: 'portal_static' } }],
  ])
  check(responses[0], { 'portal page is 200': (r) => r.status === 200 })
  check(responses[1], { 'portal asset is 200': (r) => r.status === 200 })
}

export function start_run() {
  const response = startRun('start_run')
  check(response, { 'start run is 201': (r) => r.status === 201 || r.status === 200 })
}
