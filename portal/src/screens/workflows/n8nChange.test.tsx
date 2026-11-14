import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { N8nBlockView, UseCaseView, VersionView } from '../../api/types'
import { StatusBanner } from './Banner'
import { backToVersionToast, madeWords, needsFix, refusedBanner, writeWords, yesBackToast } from './n8nChange'
import { StatusPills } from './Status'
import { Versions } from './Versions'
import { bannerOf, versionLine, type Viewer } from './workflow'

const ALICE: Viewer = { id: 'alice', operator: true, approver: true }
const BOB: Viewer = { id: 'bob', operator: false, approver: true }
const NOW = new Date('2026-11-09T11:00:00+08:00')
const nameOf = (id: string) => ({ alice: 'Alice Tan', carol: 'Carol' })[id] ?? id
const block = (kind: N8nBlockView['kind'], name: string) => ({ kind, name }) as N8nBlockView
const BASE = agentUseCase as UseCaseView
const on = { ...BASE, state: 'on', version: 4, last_run: null } as UseCaseView
const facts = (useCase: UseCaseView, viewer: Viewer = ALICE) => ({ useCase, viewer, now: NOW, nameOf })
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

describe('the workflow page’s banner for a graded version', () => {
  it('says writes are refused before the ticket, with Add the yes back for an Operator', () => {
    const refused = { ...on, grade: 'writes_refused', blocks: [block('read', 'Check releases'), block('write', 'Create ticket')] } as UseCaseView
    expect(bannerOf(facts(refused))).toEqual({ tone: 'bad', text: 'Writes refused: there’s no yes before the ticket.', action: { kind: 'yes' } })
    expect(bannerOf(facts(refused, BOB)).action).toBeNull()
  })

  it('names the write block when it is not the ticket', () => {
    expect(refusedBanner([block('write', 'Create tickets')])).toBe('Writes refused: there’s no yes before the tickets.')
    expect(refusedBanner([block('write', 'Post a comment')])).toBe('Writes refused: there’s no yes before “Post a comment”.')
    expect(writeWords([])).toBe('the write')
    expect(writeWords(undefined)).toBe('the write')
  })

  it('leads with the first finding of a version that needs a fix, and offers Undo to the version before', () => {
    const fix = { ...on, grade: 'needs_a_fix', findings: ['“Send email” is not a block we run.', 'Another.'] } as UseCaseView
    expect(bannerOf(facts(fix))).toEqual({ tone: 'bad', text: 'Needs a fix: “Send email” is not a block we run.', action: { kind: 'undo', to: 3, inUse: 4 } })
    expect(bannerOf(facts({ ...fix, version: 1 })).action, 'there is no version before the first').toBeNull()
    expect(bannerOf(facts(fix, BOB)).action).toBeNull()
  })

  it('says a workflow deleted in n8n will not run again, with no action, and says it before anything else', () => {
    const gone = { ...on, grade: 'writes_refused', deleted_in_n8n_at: '2026-11-09T01:00:00Z' } as UseCaseView
    expect(bannerOf(facts(gone))).toEqual({ tone: 'off', text: 'Deleted in n8n. It won’t run again. Its runs and versions are kept.', action: null })
  })

  it('leaves a safe version to the usual banner', () => {
    expect(bannerOf(facts({ ...on, grade: 'safe' })).tone).toBe('ok')
  })

  it('draws Add the yes back as the main button and Undo as the quiet one', () => {
    const html = (action: Parameters<typeof StatusBanner>[0]['banner']['action']) =>
      renderToStaticMarkup(<StatusBanner banner={{ tone: 'bad', text: 'x', action }} resuming={false} onResume={() => undefined} />)
    expect(html({ kind: 'yes' })).toMatch(/_primary_[^>]*>Add the yes back/)
    expect(text(html({ kind: 'undo', to: 3, inUse: 4 }))).toContain('Undo')
    expect(html({ kind: 'undo', to: 3, inUse: 4 })).not.toMatch(/_primary_/)
  })

  it('says the same words as the chat card for each grade', () => {
    expect(needsFix({ grade: 'safe' })).toBe(false)
    expect(needsFix({ grade: null })).toBe(false)
    expect(needsFix({})).toBe(false)
    expect(needsFix({ grade: 'writes_refused' })).toBe(true)
    expect(needsFix({ grade: 'needs_a_fix' })).toBe(true)
  })
})

describe('the state pill', () => {
  const pill = (props: { state: UseCaseView['state']; fix: boolean }) => text(renderToStaticMarkup(<StatusPills state={props.state} fact={null} fix={props.fix} />))
  it('reads Needs a fix while the version in use is not safe', () => {
    expect(pill({ state: 'on', fix: true })).toBe('Needs a fix')
    expect(pill({ state: 'on', fix: false })).toBe('On')
  })
  it('lets Paused win, as the sketch does', () => {
    expect(pill({ state: 'paused', fix: true })).toBe('Paused')
  })
})

describe('the Versions words', () => {
  const version = (change: Partial<VersionView>): VersionView => ({ version: 4, at: '2026-11-09T01:00:00Z', by: 'alice', via: null, change: null, undid: null, running: false, publisher_unknown: false, ...change })

  it('says a version published in n8n with what it changed and who made it', () => {
    const made = version({ made: 'published_in_n8n', changes: ['Now runs every day at 7:30.', 'Deleted “Ask for a yes”.'] })
    expect(versionLine(made, NOW, nameOf)).toBe('Today, 9:00. Changed in n8n. Now runs every day at 7:30. Deleted “Ask for a yes”. Alice Tan.')
  })

  it('says someone we don’t know when the People list could not match the publisher', () => {
    const made = version({ made: 'published_in_n8n', by: null, publisher_unknown: true, changes: ['Now runs every day at 7:30.'] })
    expect(versionLine(made, NOW, nameOf)).toBe('Today, 9:00. Changed in n8n. Now runs every day at 7:30. Someone we don’t know.')
  })

  it('says a roll back and a yes put back in the sketch’s words', () => {
    expect(madeWords({ made: 'rolled_back', rolled_back_to: 2 })).toBe('Rolled back to version 2')
    expect(madeWords({ made: 'yes_put_back' })).toBe('Put “Ask for a yes” back')
    expect(versionLine(version({ made: 'rolled_back', rolled_back_to: 2 }), NOW, nameOf)).toBe('Today, 9:00. Rolled back to version 2. Alice Tan.')
    expect(madeWords({ made: null })).toBeNull()
  })

  it('names nobody for settings saved in n8n, because n8n names nobody', () => {
    const saved = version({ made: 'settings_changed_in_n8n', by: null, changes: ['Changed its settings: the error workflow.'] })
    expect(versionLine(saved, NOW, nameOf)).toBe('Today, 9:00. Changed its settings: the error workflow. Saved in n8n, with nothing published.')
  })

  it('says what a roll back and a yes put back did, as the sketch’s messages', () => {
    expect(backToVersionToast(2, 5)).toBe('Back to version 2, saved as version 5.')
    expect(yesBackToast(5)).toBe('Version 5 has the yes back.')
  })
})

describe('Roll back in the versions list', () => {
  const versions: VersionView[] = [
    { version: 4, at: '2026-11-09T01:00:00Z', by: 'alice', via: null, change: null, undid: null, running: true, publisher_unknown: false, made: 'published_in_n8n', grade: 'writes_refused', changes: ['Deleted “Ask for a yes”.'] },
    { version: 3, at: '2026-11-08T01:00:00Z', by: 'alice', via: 'page', change: null, undid: null, running: false, publisher_unknown: false, grade: 'safe' },
    { version: 2, at: '2026-11-07T01:00:00Z', by: 'alice', via: 'page', change: null, undid: null, running: false, publisher_unknown: false },
  ]
  const draw = (operator: boolean, rows: VersionView[] = versions) => {
    const session = createDevSession(null)
    const useCase = { ...on, version: 4 }
    const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
    queryClient.setQueryData(['versions', session.cacheScope(), useCase.use_case_id, 4], rows)
    return renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
          <Versions useCase={useCase} now={NOW} nameOf={nameOf} operator={operator} say={() => undefined} />
        </ApiProvider>
      </QueryClientProvider>,
    )
  }
  const rollBacks = (html: string) => [...html.matchAll(/<button\b[^>]*>Roll back<span[^>]*> to version (\d)/g)].map((m) => m[1])

  it('puts Roll back on each n8n version but the one in use', () => {
    expect(rollBacks(draw(true))).toEqual(['3'])
  })

  it('shows an Approver no Roll back', () => {
    expect(rollBacks(draw(false))).toEqual([])
  })

  it('shows none on a workflow that runs on the shared n8n workflow', () => {
    expect(rollBacks(draw(true, versions.map((row) => ({ ...row, grade: null }))))).toEqual([])
  })

  it('says what made each version', () => {
    expect(text(draw(true))).toContain('Changed in n8n. Deleted “Ask for a yes”. Alice Tan.')
  })
})
