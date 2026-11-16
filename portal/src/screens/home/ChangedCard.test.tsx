import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import versioned from '../../../../contracts/fixtures/builder/use-case.versioned.json'
import heldInN8n from '../../../../contracts/fixtures/builder/use-case.n8n.held.json'
import type { ApiClient } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ChangedInN8nReply, Me, PersonOut, UseCaseN8nView, UseCaseView } from '../../api/types'
import { addTheYesBackOptions, rollbackOptions } from '../../api/workflowQueries'
import { Answer, type Page } from './AnswerCards'
import { CardMemoryContext, newCardMemory } from './cardMemory'
import type { Phase } from './changed'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const REFUSED = (aliceHome.changed_in_n8n as ChangedInN8nReply[])[0]!
const SAFE: ChangedInN8nReply = { ...REFUSED, grade: 'safe', findings: [], changes: ['Now runs every day at 7:30.'] }
const FIX: ChangedInN8nReply = { ...REFUSED, grade: 'needs_a_fix', findings: ['“Send email” is not a block we run.'] }

interface Drawn {
  me?: Me
  phase?: Phase
  inN8n?: UseCaseN8nView
  heldBy?: UseCaseView['held_in_n8n']
  people?: Pick<PersonOut, 'id' | 'display'>[]
}

function draw(reply: ChangedInN8nReply, { me = ALICE, phase, inN8n, heldBy = null, people }: Drawn = {}): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['use-case', session.cacheScope(), reply.use_case_id], { ...(versioned as UseCaseView), use_case_id: reply.use_case_id, held_in_n8n: heldBy })
  if (people) queryClient.setQueryData(['people', session.cacheScope()], people)
  if (inN8n) queryClient.setQueryData(['use-case', session.cacheScope(), reply.use_case_id, 'n8n'], inN8n)
  const memory = newCardMemory()
  if (phase) memory.changed.keep(phase)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <CardMemoryContext.Provider value={memory}>
            <Answer reply={reply} typed="" page={PAGE} />
          </CardMemoryContext.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const primaries = (html: string) => (html.match(/class="[^"]*_primary_[^"]*"/g) ?? []).length
const pill = (html: string) => text(/<span[^>]*data-changed-pill[^>]*>([\s\S]*?)<\/span>/.exec(html)?.[1] ?? '')

describe('the Changed in n8n card', () => {
  it('shows a safe version with its changes and only Undo', () => {
    const html = draw(SAFE)
    expect(text(html)).toContain('Changed in n8n')
    expect(pill(html)).toBe('Safe')
    expect(text(html)).toContain('FastAPI release check, version 4, by Alice Tan.')
    expect(text(html)).toContain('Now runs every day at 7:30.')
    expect(text(html)).not.toContain('refuses the write')
    expect(buttons(html)).toEqual(['Undo the change to FastAPI release check'])
    expect(primaries(html)).toBe(0)
  })

  it('shows refused writes with the sketch’s line, Add the yes back as the one main button, and Undo', () => {
    const html = draw(REFUSED)
    expect(pill(html)).toBe('Writes refused')
    expect(text(html)).toContain('Deleted “Ask for a yes”.')
    expect(text(html)).toContain('Without a yes, our platform refuses the write. The next run stops before the write.')
    expect(buttons(html)).toEqual(['Add the yes back', 'Undo the change to FastAPI release check'])
    expect(primaries(html)).toBe(1)
  })

  it('shows the findings of a version that needs a fix, and only Undo', () => {
    const html = draw(FIX)
    expect(pill(html)).toBe('Needs a fix')
    expect(text(html)).toContain('“Send email” is not a block we run.')
    expect(text(html)).not.toContain('Add the yes back')
    expect(buttons(html)).toEqual(['Undo the change to FastAPI release check'])
  })

  it('names the publisher from the People list when the card came without a name, never as an id', () => {
    const dana = 'per_01M7HH1YX20KNDD6FB2ERHWAZG'
    expect(text(draw({ ...SAFE, by: dana, by_name: null }, { people: [{ id: dana, display: 'Dana' }] }))).toContain('FastAPI release check, version 4, by Dana.')
    expect(text(draw({ ...SAFE, by: dana, by_name: null }))).toContain('FastAPI release check, version 4, by a colleague.')
  })

  it('says it does not know who published it, and never points to Settings', () => {
    const html = draw({ ...SAFE, by: null, by_name: null })
    expect(text(html)).toContain('FastAPI release check, version 4, by someone we don’t know.')
    expect(text(html)).toContain('We don’t know who published it in n8n, so its runs stop.')
    expect(text(html)).not.toMatch(/Settings|match/)
  })

  it('shows an Approver the card and no button', () => {
    const html = draw(REFUSED, { me: BOB })
    expect(text(html)).toContain('Writes refused')
    expect(buttons(html)).toEqual([])
  })

  it('says Done with the version in use once it settled, and the buttons are gone', () => {
    const html = draw(REFUSED, { phase: { kind: 'settled', version: 5 } })
    expect(text(html)).toContain('Done. Version 5 is in use.')
    expect(buttons(html)).toEqual([])
  })

  it('shows that it changed again in n8n and offers the buttons again', () => {
    const html = draw(REFUSED, { phase: { kind: 'lost', words: 'Changed again since, in n8n. Nothing was saved.' } })
    expect(text(html)).toContain('Changed again since, in n8n. Nothing was saved.')
    expect(buttons(html)).toEqual(['Add the yes back', 'Undo the change to FastAPI release check'])
  })

  it('shows another refusal in the platform’s words', () => {
    const html = draw(REFUSED, { phase: { kind: 'refused', words: 'This workflow was deleted in n8n, so it can’t change there.' } })
    expect(text(html)).toContain('This workflow was deleted in n8n, so it can’t change there.')
  })

  it('offers no button when another version is in use by now, and says which', () => {
    const html = draw({ ...REFUSED, in_use: 6 })
    expect(text(html)).toContain('Version 6 is in use now.')
    expect(buttons(html)).toEqual([])
  })

  it('names who has it open in n8n, with Take it back in place of Undo and Add the yes back, which would be refused', () => {
    const held = { ...(heldInN8n as UseCaseN8nView), editor_url: null }
    const heldBy = held.holder
    const html = draw(REFUSED, { me: { ...ALICE, n8n_access: true }, inN8n: held, heldBy })
    expect(text(html)).toMatch(/Carol has it open in n8n since (Tue 10 Nov, )?13:40\. Anyone with n8n access can take it back from Carol\./)
    expect(buttons(html)).toEqual(['Take it back'])
    const theirs = draw(REFUSED, { me: { ...ALICE, n8n_access: true }, inN8n: { ...held, can_open: false, why_not: 'Set your n8n password first.' }, heldBy })
    expect(buttons(theirs), 'nobody is offered a press the platform would refuse').toEqual([])
    expect(buttons(draw({ ...REFUSED, in_use: 6 }, { me: { ...ALICE, n8n_access: true }, inN8n: held, heldBy })), 'a card about a version no longer in use offers nothing').toEqual([])
  })

  it('tells an Operator without n8n access who holds it and who can take it back, before she presses anything', () => {
    const heldBy = (heldInN8n as UseCaseN8nView).holder
    const html = draw(REFUSED, { heldBy })
    expect(text(html)).toMatch(/Carol has it open in n8n since (Tue 10 Nov, )?13:40\. Ask Carol, or anyone with n8n access, to take it back\./)
    expect(buttons(html), 'Undo and Add the yes back would be refused, so neither is offered').toEqual([])
  })

  it('tells an Operator without n8n access who can take it back, with no press she can’t make', () => {
    const words = 'Carol has it open in n8n since 13:40. Ask Carol, or anyone with n8n access, to take it back.'
    const html = draw(REFUSED, { phase: { kind: 'refused', words } })
    expect(text(html)).toContain(words)
    expect(buttons(html)).not.toContain('Take it back')
  })

  it('uses no em dash', () => {
    for (const html of [draw(SAFE), draw(REFUSED), draw(FIX)]) expect(text(html)).not.toContain('—')
  })
})

describe('what Undo and Add the yes back ask the platform', () => {
  const view = { ...(versioned as UseCaseView), version: 6 }
  const answered = Promise.resolve({ data: view, response: { ok: true, status: 200 } })

  it('rolls back to the version before, saying which version it saw in use and that the chat asked', async () => {
    const sent: unknown[] = []
    const client = { POST: (path: string, init: unknown) => (sent.push([path, init]), answered) } as unknown as ApiClient
    await rollbackOptions(client, new QueryClient(), 'me').mutationFn({ useCaseId: 'uc_fastapi', version: 3, inUse: 4, via: 'chat' })
    expect(sent).toEqual([['/api/v1/use-cases/{use_case_id}/versions/{version}/rollback', { params: { path: { use_case_id: 'uc_fastapi', version: 3 } }, body: { via: 'chat', in_use: 4 } }]])
  })

  it('puts the yes back with the version it saw in use', async () => {
    const sent: unknown[] = []
    const client = { POST: (path: string, init: unknown) => (sent.push([path, init]), answered) } as unknown as ApiClient
    await addTheYesBackOptions(client, new QueryClient(), 'me').mutationFn({ useCaseId: 'uc_fastapi', inUse: 4, via: 'page' })
    expect(sent).toEqual([['/api/v1/use-cases/{use_case_id}/add-the-yes-back', { params: { path: { use_case_id: 'uc_fastapi' } }, body: { via: 'page', in_use: 4 } }]])
  })
})
