import { expect, request, type APIRequestContext } from '@playwright/test'

export const MOCK_GITHUB_URL = process.env['MOCK_GITHUB_URL'] ?? 'http://mock-github:8200'
/** platform-api waits this long before it re-runs a failed leg (operator_retry_delay in orchestration/dispatch.py). */
export const PLATFORM_RETRY_DELAY_MS = 3_000

type Json = Record<string, unknown>

export interface RunSnapshot {
  run_id: string
  state: string
  use_case_name: string
  started_by: string
  reason?: string | null
  retryable?: boolean | null
  stage?: string | null
  outcome?: string | null
}

export interface Ticket {
  key: string
  title: string
  body: string
  run_id: string
}

export interface TeamsMessage {
  id: string
  text: string
  link: string
  channel: string
  run_id: string
  approval_id: string
}

export type Proof = Readonly<Record<string, string>>

/** The backend as the Portal sees it: through the Portal's own address, so the nginx proxy is part of the check. */
export class Backend {
  private readonly http: APIRequestContext
  private readonly proofs = new Map<string, Proof>()

  private constructor(http: APIRequestContext) {
    this.http = http
  }

  proofOf(user: string): Proof {
    return this.proofs.get(user) ?? { 'X-Dev-User': user }
  }

  signedIn(user: string, proof: Proof): void {
    this.proofs.set(user, proof)
  }

  static async connect(baseURL: string): Promise<Backend> {
    return new Backend(await request.newContext({ baseURL }))
  }

  async dispose(): Promise<void> {
    await this.http.dispose()
  }

  async get<T = Json>(user: string, path: string): Promise<T> {
    const response = await this.http.get(path, { headers: this.proofOf(user) })
    expect(response.status(), `GET ${path} as ${user}`).toBe(200)
    return (await response.json()) as T
  }

  async runs(user = 'alice'): Promise<RunSnapshot[]> {
    return (await this.get<{ runs: RunSnapshot[] }>(user, '/api/v1/runs')).runs
  }

  run(runId: string, user = 'alice'): Promise<RunSnapshot> {
    return this.get<RunSnapshot>(user, `/api/v1/runs/${runId}`)
  }

  async tickets(): Promise<Ticket[]> {
    return (await this.get<{ tickets: Ticket[] }>('alice', '/api/v1/mock-jira/tickets')).tickets
  }

  async teamsMessages(): Promise<TeamsMessage[]> {
    return (await this.get<{ messages: TeamsMessage[] }>('alice', '/api/v1/teams-stub/messages')).messages
  }

  async approvalIdOf(runId: string): Promise<string> {
    const { events } = await this.get<{ events: { kind: string; data: { approval_id?: string } }[] }>(
      'alice',
      `/api/v1/runs/${runId}/events?after=0`,
    )
    const requested = events.find((event) => event.kind === 'approval_requested')
    expect(requested, `run ${runId} has asked for an approval`).toBeDefined()
    return requested?.data.approval_id ?? ''

  }

  /** Polls until the run has left a state, for the moment between a click on Retry and the platform acting on it. */
  async waitToLeave(runId: string, state: string, timeoutMs = 15_000): Promise<void> {
    await expect
      .poll(async () => (await this.run(runId)).state, { message: `run ${runId} leaves ${state}`, timeout: timeoutMs, intervals: [250] })
      .not.toBe(state)
  }

  /** Polls the run until it is in one of the states, and fails early if it ends somewhere else. */
  async waitForState(runId: string, states: readonly string[], timeoutMs = 90_000): Promise<RunSnapshot> {
    const ended = ['succeeded', 'rejected', 'failed']
    let last: RunSnapshot | undefined
    await expect
      .poll(
        async () => {
          last = await this.run(runId)
          if (!states.includes(last.state) && ended.includes(last.state)) {
            throw new Error(`run ${runId} ended as ${last.state} (${last.reason ?? 'no failure reason'}), wanted ${states.join(' or ')}`)
          }
          return states.includes(last.state)
        },
        { message: `run ${runId} reaches ${states.join(' or ')}`, timeout: timeoutMs, intervals: [500] },
      )
      .toBe(true)
    return last as RunSnapshot
  }
}

export async function setMockGithubMode(mode: 'ok' | 'unavailable'): Promise<void> {
  const http = await request.newContext()
  try {
    const response = await http.post(`${MOCK_GITHUB_URL}/_admin/mode`, { data: { mode } })
    expect(response.status(), `mock-github accepts mode ${mode}`).toBe(200)
  } finally {
    await http.dispose()
  }
}
