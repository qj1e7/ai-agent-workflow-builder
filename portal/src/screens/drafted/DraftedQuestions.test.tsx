import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import inN8n from '../../../../contracts/fixtures/builder/drafted.in-n8n.json'
import question from '../../../../contracts/fixtures/builder/drafted.question.json'
import ready from '../../../../contracts/fixtures/builder/drafted.ready.json'
import { ApiProvider } from '../../api/context'
import { draftedKey, useAnswerDrafted, useDoneInN8n, useEditInN8n } from '../../api/draftedQueries'
import { createDevSession } from '../../api/session'
import type { DraftedWorkflowView, DraftSettingView } from '../../api/types'
import { ChatProvider } from '../home/ChatProvider'
import { threadReducer, EMPTY } from '../home/threadState'
import { DraftedCard } from './DraftedCard'
import { draftedPill, inN8nWords, questionOf, typedPlaceholder } from './drafted'

const scope = createDevSession(null).cacheScope()
const QUESTION = question as DraftedWorkflowView
const READY = ready as DraftedWorkflowView
const IN_N8N = inN8n as DraftedWorkflowView

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))

function within(node: ReactNode, queryClient = new QueryClient(), platform: (request: Request) => Response = () => json({})): string {
  const answer = (input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(platform(new Request(input, init)))
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={createDevSession(null)} platformFetch={answer} origin="http://portal.test" baseUrl="http://portal.test">
        <MemoryRouter>
          <ChatProvider>{node}</ChatProvider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const card = (view: DraftedWorkflowView, revision = view.card_revision) => {
  const queryClient = new QueryClient()
  queryClient.setQueryData(draftedKey(scope, view.drafted_id), view)
  return within(<DraftedCard draftedId={view.drafted_id} revision={revision} />, queryClient)
}

const withSetting = (view: DraftedWorkflowView, id: string, change: Partial<DraftSettingView>): DraftedWorkflowView => ({
  ...view,
  settings: view.settings.map((setting) => (setting.id === id ? { ...setting, ...change } : setting)),
})

describe('what came back from n8n that did not count', () => {
  it('says each one on the card, above the question it asks again', () => {
    const said = 'You typed “#random” in n8n for “Slack channel”, but that isn’t a Slack channel the platform’s key can see. So it’s asked again.'
    const html = card({ ...QUESTION, notes: [said] })
    expect(html).toContain('data-n8n-notes')
    expect(text(html)).toContain('You typed “#random” in n8n for “Slack channel”')
    expect(text(html).indexOf('You typed')).toBeLessThan(text(html).indexOf('Mondays, at what time?'))
  })

  it('says nothing when everything counted', () => {
    expect(card(QUESTION)).not.toContain('data-n8n-notes')
  })
})

describe('the question a draft asks', () => {
  it('asks the run time first, with a button for each time and one to type a time', () => {
    const html = card(QUESTION)
    expect(text(html)).toContain('When Mondays, at what time?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['8:00', '9:00', '13:00', '17:00', 'Type a time']))
    expect(text(html)).not.toContain('Who says yes')
    expect(buttons(html)).not.toContain('Send for approval')
    expect(text(html)).toContain('Answer 2 questions first')
    expect(html).not.toContain('disabled')
  })

  it('asks one question at a time, the one the platform names', () => {
    const second = { ...withSetting(QUESTION, 'run_time', { mark: 'filled', value: 'every Monday at 9:00', said: 'You chose' }), question: 'approvers' }
    expect(questionOf(second)?.id).toBe('approvers')
    const html = card(second)
    expect(text(html)).toContain('Yes from Who says yes to “Make the ticket” on each run?')
    expect(buttons(html)).toContain('Any Approver on the team')
    expect(buttons(html)).not.toContain('Type a time')
  })

  it('asks nothing, and offers Send for approval, once nothing is needed', () => {
    const html = card(READY)
    expect(html).not.toContain('aria-label="Settings"')
    expect(buttons(html)).toContain('Send for approval')
  })

  it('asks nothing of a draft that is waiting for a yes', () => {
    const html = card({ ...QUESTION, state: 'waiting' })
    expect(text(html)).not.toContain('Mondays, at what time?')
  })

  it('reads the typed time with its own words in the box', () => {
    expect(typedPlaceholder('run_time')).toBe('Like 7:45 or 6pm')
    expect(typedPlaceholder('repository')).toBe('Type it here')
  })
})

describe('a guess, and a setting that waits', () => {
  it('shows a guess as a guess, with a Change button that names its setting', () => {
    const html = card(withSetting(READY, 'run_time', { mark: 'guessed', said: 'I guessed' }))
    expect(text(html)).toContain('When every Monday at 9:00 I guessed. Change')
    expect(html).toContain('aria-label="Change When"')
    expect(html).toContain('aria-expanded="false"')
  })

  it('shows a needed setting that waits with its reason and nothing to press', () => {
    const key: DraftSettingView = {
      id: 'key',
      kind: 'key',
      key: 'Key',
      label: [{ text: 'The Jira write key', quoted: true }],
      value: null,
      mark: 'needed',
      said: 'Needed',
      question: 'Which key should it write with?',
      choices: [],
      typed: null,
      waits: 'Waits until an Operator adds a Jira write key in Settings.',
    }
    const html = card({ ...READY, settings: [...READY.settings, key], question: null, needed: 1, can_send: false, why_not_send: 'Waiting for an Operator to add a key' })
    expect(text(html)).toContain('Key “The Jira write key” Waits until an Operator adds a Jira write key in Settings.')
    expect(text(html)).toContain('Waiting for an Operator to add a key')
    expect(buttons(html)).not.toContain('Send for approval')
  })
})

describe('Edit in n8n', () => {
  it('shows only when the platform says this person can', () => {
    expect(buttons(card(READY))).toContain('Edit in n8n')
    expect(buttons(card({ ...READY, can_edit_in_n8n: false }))).not.toContain('Edit in n8n')
  })

  it('shows the person who opened it a link to n8n and Done in n8n, in place of Send and Ask for a change', () => {
    const html = card(IN_N8N)
    expect(text(html)).toContain('Revision 2 In n8n')
    expect(text(html)).toContain('Open in your own n8n space, without its keys.')
    expect(html).toContain('href="https://n8n.example/workflow/wfDraftEdit01"')
    expect(html).toContain('target="_blank"')
    expect(buttons(html)).toEqual(['See the report', 'Open n8n (opens in a new tab)', 'Done in n8n'])
    expect(text(html)).not.toContain('Answer')
  })

  it('says which n8n login Open n8n uses, and nothing when the login is unknown', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(draftedKey(scope, IN_N8N.drafted_id), IN_N8N)
    queryClient.setQueryData(['me', scope], { id: 'carol', display: 'Carol', roles: ['operator'], n8n_access: true, n8n_login: 'dana.n8ntest@example.test' })
    const html = within(<DraftedCard draftedId={IN_N8N.drafted_id} revision={IN_N8N.card_revision} />, queryClient)
    expect(text(html)).toContain('Opens in n8n as dana.n8ntest@example.test.')
    queryClient.setQueryData(['me', scope], { id: 'carol', display: 'Carol', roles: ['operator'], n8n_access: true, n8n_login: null })
    const unknown = within(<DraftedCard draftedId={IN_N8N.drafted_id} revision={IN_N8N.card_revision} />, queryClient)
    expect(unknown).toContain('Open n8n')
    expect(text(unknown)).not.toMatch(/Opens in n8n as/)
  })

  it('tells anyone else who has it open, with no buttons for it', () => {
    const html = card({ ...IN_N8N, in_n8n: { ...IN_N8N.in_n8n!, editor_url: null } })
    expect(text(html)).toContain('Carol has it open in n8n.')
    expect(buttons(html)).toEqual(['See the report'])
  })

  it('has its own pill, while the server state stays draft', () => {
    expect(draftedPill('draft', true)).toEqual({ label: 'In n8n', tone: 'quiet' })
    expect(draftedPill('draft')).toEqual({ label: 'Draft', tone: 'quiet' })
    expect(inN8nWords(READY)).toBeNull()
  })
})

describe('which card shows the newest view', () => {
  it('shows the newest view on a card for the revision that started it, headed with the newest revision', () => {
    const html = card({ ...READY, revision: 3, card_revision: 1 }, 1)
    expect(text(html)).toContain('Revision 3 Draft')
    expect(text(html)).not.toContain('is below')
  })

  it('settles a card once a newer card started, naming that card’s revision', () => {
    const html = card({ ...READY, revision: 4, card_revision: 3 }, 1)
    expect(text(html)).toContain('Revision 1. Revision 3 is below.')
    expect(buttons(html)).toEqual([])
  })

  it('puts a new card in the thread, with no message of theirs before it', () => {
    const next = threadReducer(EMPTY, { type: 'draft_card', draftedId: 'dw_1', revision: 3 })
    expect(next.messages).toEqual([{ kind: 'drafted', id: 1, draftedId: 'dw_1', revision: 3 }])
  })
})

describe('the answers it sends', () => {
  async function run<T>(use: () => { mutateAsync: (input: never) => Promise<unknown> } & T, call: (probe: T) => Promise<unknown>, platform: (request: Request) => Response) {
    const queryClient = new QueryClient()
    let probe: T | undefined
    function Probe() {
      probe = use()
      return null
    }
    within(<Probe />, queryClient, platform)
    const result = await call(probe as T).then(
      (value) => ({ value, error: null }),
      (error: unknown) => ({ value: null, error }),
    )
    return { queryClient, result }
  }

  it('sends the revision, the setting and one choice, and keeps the new view', async () => {
    const taken = { ...READY, revision: 3 }
    const seen: { path: string; body: Promise<unknown> }[] = []
    const { queryClient, result } = await run(
      () => useAnswerDrafted('dw_01JDRAFTRELEASE'),
      (probe) => probe.mutateAsync({ revision: 2, setting: 'run_time', choice: '09:00' }),
      (request) => {
        seen.push({ path: new URL(request.url).pathname, body: request.clone().json() })
        return json(taken)
      },
    )
    expect(result.error).toBeNull()
    expect(seen[0]?.path).toBe('/api/v1/drafted-workflows/dw_01JDRAFTRELEASE/answers')
    await expect(seen[0]?.body).resolves.toEqual({ revision: 2, setting: 'run_time', choice: '09:00' })
    expect(queryClient.getQueryData(draftedKey(scope, 'dw_01JDRAFTRELEASE'))).toEqual(taken)
  })

  it('opens it in n8n with the revision, and reads it back with no body', async () => {
    const paths: string[] = []
    const platform = (request: Request) => {
      paths.push(`${request.method} ${new URL(request.url).pathname}`)
      return json(IN_N8N)
    }
    await run(() => useEditInN8n('dw_01JDRAFTRELEASE'), (probe) => probe.mutateAsync(2), platform)
    await run(() => useDoneInN8n('dw_01JDRAFTRELEASE'), (probe) => probe.mutateAsync(undefined as never), platform)
    expect(paths).toEqual(['POST /api/v1/drafted-workflows/dw_01JDRAFTRELEASE/n8n', 'POST /api/v1/drafted-workflows/dw_01JDRAFTRELEASE/n8n/done'])
  })

  it('refuses with the platform’s words, which stay under the box', async () => {
    const { result } = await run(
      () => useAnswerDrafted('dw_01JDRAFTRELEASE'),
      (probe) => probe.mutateAsync({ revision: 2, setting: 'run_time', typed: '9' }),
      () => json({ detail: 'I couldn’t read a time in that. Try 7:45 or 6pm.' }, 409),
    )
    expect(result.error).toBeTruthy()
  })
})
