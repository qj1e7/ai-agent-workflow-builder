import type { CreateUseCase, DevUser, Verdict } from '../api/types'
import { fixtures } from './fixtures'
import { invalid, isRecord, json, problem, type MockRequest } from './http'
import type { DemoPlatform } from './platform'
import { streamEvents } from './stream'

const API_PREFIX = '/api/v1'
const NOBODY: DevUser = { id: 'nobody', display: 'Nobody', roles: [] }

interface Call {
  readonly platform: DemoPlatform
  readonly request: MockRequest
  readonly params: readonly string[]
  readonly wall: number
  readonly user: DevUser
}

type Handler = (call: Call) => Response

interface Route {
  readonly method: string
  readonly pattern: RegExp
  readonly open: boolean
  readonly handler: Handler
}

function route(method: string, path: string, handler: Handler, open = false): Route {
  const pattern = new RegExp(`^${path.replace(/\{[^}]+\}/g, '([^/]+)')}$`)
  return { method, pattern, open, handler }
}

function asStrings(value: unknown): Record<string, string> | undefined {
  if (!isRecord(value)) return undefined
  const entries = Object.entries(value)
  return entries.every(([, item]) => typeof item === 'string') ? (value as Record<string, string>) : undefined
}

function parseUseCase(body: unknown): CreateUseCase | undefined {
  if (!isRecord(body)) return undefined
  const { template, name, instruction } = body
  const params = asStrings(body['params'])
  if (typeof template !== 'string' || typeof name !== 'string' || typeof instruction !== 'string' || !params) {
    return undefined
  }
  return { template, name, instruction, params }
}

function parseVerdict(value: unknown): Verdict | undefined {
  return value === 'approve' || value === 'decline' ? value : undefined
}

const routes: readonly Route[] = [
  route('GET', '/dev/users', () => json(200, { users: fixtures.devUsers }), true),
  route('GET', '/me', ({ user }) => json(200, user)),
  route('GET', '/templates', () => json(200, { templates: fixtures.templates }), true),
  route('GET', '/use-cases', ({ platform }) => json(200, { use_cases: platform.listUseCases() })),
  route('POST', '/use-cases/suggest', ({ platform, request }) => {
    const text = isRecord(request.body) ? request.body['text'] : undefined
    return typeof text === 'string' ? json(200, platform.suggest(text)) : invalid('text must be a string')
  }),
  route('POST', '/use-cases', ({ platform, request, user, wall }) => {
    const input = parseUseCase(request.body)
    if (!input) return invalid('template, name, instruction and params are required')
    if (!fixtures.templates.some((template) => template.key === input.template)) return invalid('unknown template')
    const created = platform.createUseCase(user, input, wall)
    return json(201, { use_case_id: created.use_case_id, version: created.version })
  }),
  route('GET', '/use-cases/{id}', ({ platform, params }) => {
    const useCase = platform.useCase(params[0] ?? '')
    return useCase ? json(200, useCase) : problem(404, 'There is no such use case.')
  }),
  route('POST', '/use-cases/{id}/runs', ({ platform, request, params, user, wall }) => {
    const key = request.headers.get('Idempotency-Key')
    if (!key) return invalid('The Idempotency-Key header is required')
    const run = platform.startRun(user, params[0] ?? '', key, wall)
    if (!run) return problem(404, 'There is no such use case.')
    return json(201, { run_id: run.id, state: 'pending', events_url: `${API_PREFIX}/runs/${run.id}/events` })
  }),
  route('GET', '/runs', ({ platform, wall }) => json(200, { runs: platform.listRuns(wall) })),
  route('GET', '/runs/{id}', ({ platform, params, wall }) => {
    const run = platform.run(params[0] ?? '')
    return run ? json(200, run.view(wall)) : problem(404, 'There is no such run.')
  }),
  route('GET', '/runs/{id}/events', ({ platform, request, params, wall }) => {
    const run = platform.run(params[0] ?? '')
    if (!run) return problem(404, 'There is no such run.')
    const after = Math.max(Number(request.query.get('after')) || 0, Number(request.headers.get('Last-Event-ID')) || 0)
    if (request.headers.get('Accept')?.includes('text/event-stream')) {
      return streamEvents(run.timeline, after, request.signal)
    }
    return json(200, { events: run.timeline.emitted(wall).filter((event) => event.seq > after) })
  }),
  route('POST', '/runs/{id}/retry', ({ platform, params, user, wall }) => {
    const result = platform.retry(user, params[0] ?? '', wall)
    if (result.kind === 'not_found') return problem(404, 'There is no such run.')
    if (result.kind === 'not_retryable') return problem(409, 'Only a stopped run that can be retried may be retried.')
    return json(202, { state: 'pending' })
  }),
  route('GET', '/runs/{id}/troubleshoot', ({ platform, params, wall }) => {
    const run = platform.run(params[0] ?? '')
    if (!run) return problem(404, 'There is no such run.')
    const view = run.view(wall)
    if (view.state !== 'failed') return problem(404, 'This run has not failed.')
    const { stage, reason, retryable, message } = view
    return json(200, { ...fixtures.troubleshooting, run_id: run.id, failure: { stage, reason, retryable, message } })
  }),
  route('GET', '/approvals/{id}', ({ platform, params, user, wall }) => {
    const approval = platform.approval(params[0] ?? '', user, wall)
    return approval ? json(200, approval) : problem(404, 'There is no such approval.')
  }),
  route('POST', '/approvals/{id}/decisions', ({ platform, request, params, user, wall }) => {
    const body = request.body
    const verdict = isRecord(body) ? parseVerdict(body['verdict']) : undefined
    const step = isRecord(body) ? body['step'] : undefined
    const digest = isRecord(body) ? body['digest'] : undefined
    if (!verdict || typeof step !== 'number' || typeof digest !== 'string') {
      return invalid('step, verdict and digest are required')
    }
    const result = platform.decide(user, params[0] ?? '', step, verdict, digest, wall)
    switch (result.kind) {
      case 'not_found':
        return problem(404, 'There is no such approval.')
      case 'refused':
        return json(403, { refusal: result.refusal, message: result.message })
      case 'conflict':
        return problem(409, 'Another Approver decided this step first.')
      case 'recorded':
        return json(result.created ? 201 : 200, result.out)
    }
  }),
  route('GET', '/teams-stub/messages', ({ platform, wall }) => json(200, { messages: platform.teamsMessages(wall) })),
  route('GET', '/mock-jira/tickets', ({ platform, wall }) => json(200, { tickets: platform.jiraTickets(wall) })),
  route('GET', '/settings/model', ({ platform, user }) => json(200, platform.modelSettings.view(user))),
  route('POST', '/settings/model/connect', ({ platform, request, user }) =>
    platform.modelSettings.connect(user, request.body),
  ),
  route('PUT', '/settings/model', ({ platform, request, user, wall }) =>
    platform.modelSettings.save(user, request.body, wall),
  ),
  route('DELETE', '/settings/model', ({ platform, user, wall }) => platform.modelSettings.turnOff(user, wall)),
  route('POST', '/settings/model/address-decision', ({ platform, request, user, wall }) =>
    platform.modelSettings.decide(user, request.body, wall),
  ),
]

export function dispatch(platform: DemoPlatform, request: MockRequest, wall: number): Response {
  if (!request.path.startsWith(`${API_PREFIX}/`)) return problem(404, 'The demo platform only serves the API.')
  const path = request.path.slice(API_PREFIX.length)
  for (const candidate of routes) {
    const match = candidate.pattern.exec(path)
    if (!match || candidate.method !== request.method) continue
    const user = platform.user(request.headers.get('X-Dev-User'))
    if (!user && !candidate.open) return problem(401, 'Sign in as one of the dev users.')
    return candidate.handler({ platform, request, params: match.slice(1), wall, user: user ?? NOBODY })
  }
  return problem(404, 'There is no such endpoint.')
}
