import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import confirmationsAlice from '../../../../contracts/fixtures/people/confirmations.alice.json'
import confirmationsBob from '../../../../contracts/fixtures/people/confirmations.bob.json'
import list from '../../../../contracts/fixtures/people/list.json'
import personApprover from '../../../../contracts/fixtures/people/person.approver.json'
import history from '../../../../contracts/fixtures/settings/history.json'
import modelActive from '../../../../contracts/fixtures/settings/model.active.json'
import modelEmpty from '../../../../contracts/fixtures/settings/model.empty.json'
import pendingAlice from '../../../../contracts/fixtures/settings/model.pending.alice.json'
import pendingBob from '../../../../contracts/fixtures/settings/model.pending.bob.json'
import { App } from '../../App'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ConfirmationOut, Me, ModelOut, PersonOut } from '../../api/types'
import { MODEL_READ_ONLY_WORDS, NO_MODEL_WORDS, notNowWords } from './ModelTab'
import { PEOPLE_LEAD } from './PeopleTab'
import { ONLY_OPERATORS_WORDS, SETTINGS_OFF_WORDS } from './settings'
import { SettingsTabs } from './SettingsTabs'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'], on_list: true }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'], on_list: true }
const CAROL: Me = { id: 'carol', display: 'Carol', roles: ['operator'], on_list: true }

const PEOPLE = list.people as PersonOut[]
const DAVE_ID = 'per_01JD4VE'
const withDave = (dave: PersonOut) => PEOPLE.map((person) => (person.id === DAVE_ID ? dave : person))
const CONFIRMED = withDave(personApprover)
const NOT_NOW = withDave({ ...(personApprover as PersonOut), approver: false })
const approverOnly = (confirmations: { confirmations: unknown[] }) =>
  (confirmations.confirmations as ConfirmationOut[]).filter((entry) => entry.kind === 'approver')

interface Setup {
  readonly me?: Me
  readonly tab?: 'model' | 'people'
  readonly model?: unknown
  readonly people?: PersonOut[]
  readonly confirmations?: ConfirmationOut[]
}

function render({ me = ALICE, tab = 'model', model = modelActive, people = PEOPLE, confirmations = [] }: Setup = {}): string {
  const session = createDevSession({ getItem: () => me.id, setItem: () => undefined })
  const user = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', user], me)
  queryClient.setQueryData(['model-settings', user], model)
  queryClient.setQueryData(['people', user], people)
  queryClient.setQueryData(['confirmations', user], confirmations)
  queryClient.setQueryData(['settings-history', user], history.changes)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[tab === 'people' ? '/settings?tab=people' : '/settings']}>
          <SettingsTabs />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) =>
  html
    .replace(/<[^>]*>/g, ' ')
    .replaceAll('&#x27;', "'")
    .replaceAll('&amp;', '&')
    .replace(/\s+/g, ' ')
    .replace(/ ([,.])/g, '$1')
    .trim()
const boxOf = (html: string, id: string) => new RegExp(`<input[^>]*id="${id}"[^>]*>`).exec(html)?.[0] ?? ''
const rowOf = (html: string, name: string) => [...html.matchAll(/<li class="[^"]*person[^"]*">([\s\S]*?)<\/li>/g)].map((match) => match[1] ?? '').find((row) => row.includes(`<b>${name}`)) ?? ''
const checkboxes = (html: string) => [...html.matchAll(/<input[^>]*type="checkbox"[^>]*>/g)].map((match) => match[0])
const buttonsIn = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))

describe('the Settings tabs', () => {
  it('offer the AI model and People and roles, with the one shown marked pressed', () => {
    const html = render()
    expect(html).toMatch(/role="group" aria-label="Settings sections"/)
    expect(html).toMatch(/<button type="button" aria-pressed="true">AI model/)
    expect(html).toMatch(/<button type="button" aria-pressed="false">People and roles/)
    expect(render({ tab: 'people' })).toMatch(/<button type="button" aria-pressed="true">People and roles/)
  })

  it('mark the tabs that need the viewer', () => {
    const bob = render({ me: BOB, model: pendingBob, confirmations: confirmationsBob.confirmations as ConfirmationOut[] })
    expect(bob.match(/\(needs you\)/g)).toHaveLength(2)
    const alice = render({ model: pendingAlice, confirmations: confirmationsAlice.confirmations as ConfirmationOut[] })
    expect(alice).not.toContain('(needs you)')
  })

  it('never mark the AI model for the person whose own address waits, even with no model yet', () => {
    expect(render({ model: { ...pendingAlice, active: null } })).not.toContain('(needs you)')
    expect(render({ me: BOB, model: { ...pendingBob, active: null } }).match(/\(needs you\)/g)).toHaveLength(1)
  })

  it('load the Settings page itself in the shell, with its heading at once', () => {
    const queryClient = new QueryClient()
    const session = createDevSession(null)
    queryClient.setQueryData(['me', session.cacheScope()], ALICE)
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
          <MemoryRouter initialEntries={['/settings']}>
            <App />
          </MemoryRouter>
        </ApiProvider>
      </QueryClientProvider>,
    )
    expect(html).toMatch(/<h1 tabindex="-1">Settings<\/h1>/)
    expect(text(html)).toContain('Every change here is recorded with who made it.')
  })
})

describe('the AI model tab', () => {
  it('shows the model in use with only the last 2 characters of its key', () => {
    const main = text(render())
    expect(main).toContain('Connected')
    expect(main).toContain('AI Singapore gateway · claude-haiku-5-5')
    expect(main).toContain('API key ending x7. Saved by Alice on Mon 2 Nov. It answered the test in 1.4 s.')
  })

  it('never shows more of a key than its last 2 characters', () => {
    const longHint = { ...modelActive, active: { ...modelActive.active, key_hint: 'not-a-key-xyz9c' } }
    const html = render({ model: longHint })
    expect(html).toContain('API key ending 9c')
    expect(html).not.toContain('not-a-key')
    expect(html).not.toContain('xyz9c')
  })

  it('offers Connect with every known provider and another address, and a key field that holds no value', () => {
    const html = render()
    const main = text(html)
    expect(main).toContain('Change the model or key')
    for (const name of ['AI Singapore gateway', 'OpenAI', 'Anthropic', 'Google Gemini', 'Another address']) expect(main).toContain(name)
    const key = /<input[^>]*id="model-key"[^>]*>/.exec(html)?.[0] ?? ''
    expect(key).toContain('type="password"')
    expect(key).toMatch(/autocomplete="off"/i)
    expect(key).not.toMatch(/\svalue=/)
    expect(main).toContain('Leave it empty to keep the key ending x7.')
    expect(buttonsIn(html)).toContain('Connect')
  })

  it('says what runs do until a model is connected', () => {
    const main = text(render({ model: modelEmpty }))
    expect(main).toContain('Not connected')
    expect(main).toContain(NO_MODEL_WORDS)
    // An agent workflow run gets 409 "Connect an AI model in Settings to run agents." Only the watchlist summary has a template.
    expect(main).toContain('Until you connect one, agent workflows can’t run and new workflows can’t be planned.')
    expect(main).toContain('Only the Software watchlist’s summary uses a simple template instead.')
    expect(main).not.toMatch(/simple text from templates|keep using simple templates/)
    expect(main).toContain('Connect a model')
    expect(main).not.toContain('Leave it empty')
  })

  it('shows a new address waiting for an Approver to the person who entered it, who cannot confirm it', () => {
    const html = render({ model: pendingAlice })
    const main = text(html)
    expect(main).toContain('A new address is waiting for an Approver')
    expect(main).toContain('https://ai-gateway.ncs.example/v1 · ncs-llm-small. Entered by Alice.')
    expect(main).toContain('runs keep using claude-haiku-5-5')
    expect(main).toContain('You entered this address, so another Approver must confirm it.')
    expect(buttonsIn(html)).not.toContain('Confirm address')
  })

  it('says agent workflows can’t run while the first address waits, and that only the watchlist summary has a template', () => {
    const main = text(render({ model: { ...pendingAlice, active: null } }))
    expect(main).toContain('Until then, agent workflows can’t run, and only the Software watchlist’s summary uses a simple template.')
    expect(main).not.toContain('keep using simple templates')
  })

  it('says what runs use after not now, with a model and without one', () => {
    expect(notNowWords(modelActive.active as ModelOut)).toBe('You said not now. Runs keep using claude-haiku-5-5.')
    expect(notNowWords(null)).toBe('You said not now. Agent workflows can’t run, and only the Software watchlist’s summary uses a simple template.')
  })

  it('lets an Approver who did not ask confirm the address or say not now, read-only otherwise', () => {
    const html = render({ me: BOB, model: pendingBob })
    expect(buttonsIn(html)).toEqual(expect.arrayContaining(['Not now', 'Confirm address']))
    const main = text(html)
    expect(main).toContain(MODEL_READ_ONLY_WORDS)
    expect(main).toContain(ONLY_OPERATORS_WORDS)
    expect(html).not.toContain('<form')
    expect(html).not.toContain('<select')
    expect(html).not.toContain('<input')
  })

  it('says when the platform has the settings switched off', () => {
    const off = { ...modelEmpty, available: false, unavailable_message: 'Settings are off until SETTINGS_ENCRYPTION_KEY is set for platform-api.', you_can_change: false }
    const html = render({ model: off })
    expect(text(html)).toContain(SETTINGS_OFF_WORDS)
    expect(html).not.toContain('SETTINGS_ENCRYPTION_KEY')
    expect(html).not.toContain('<form')
  })

  it('keeps a history that never holds a key', () => {
    const main = text(render())
    expect(main).toContain('Change history')
    expect(main).toContain('The history never holds a key, only its last 2 characters.')
  })
})

describe('the People and roles tab', () => {
  it('lists everyone with their roles, and says who has not signed in yet', () => {
    const html = render({ tab: 'people', confirmations: approverOnly(confirmationsAlice) })
    const main = text(html)
    expect(main).toContain(PEOPLE_LEAD)
    for (const name of ['Alice', 'Bob', 'Carol', 'Dave']) expect(rowOf(html, name)).not.toBe('')
    expect(text(rowOf(html, 'Alice'))).toContain('You')
    expect(text(rowOf(html, 'Dave'))).toContain('Hasn’t signed in yet')
    expect(text(rowOf(html, 'Bob'))).not.toContain('Hasn’t signed in yet')
    const bob = rowOf(html, 'Bob')
    expect(boxOf(bob, 'person-bob-operator')).not.toContain('checked')
    expect(boxOf(bob, 'person-bob-approver')).toContain('checked=""')
    expect(text(bob)).toContain('Operator for Bob')
  })

  it('shows a pending Approver to the Operator who asked, who cannot confirm it', () => {
    const html = render({ tab: 'people', confirmations: approverOnly(confirmationsAlice) })
    const dave = rowOf(html, 'Dave')
    expect(text(dave)).toContain('Approver: waiting for another Approver to confirm')
    expect(text(dave)).toContain('Asked by you, so another Approver must confirm it.')
    expect(buttonsIn(dave)).toEqual([])
    expect(boxOf(dave, 'person-per_01JD4VE-approver')).toContain('checked=""')
    expect(boxOf(dave, 'person-per_01JD4VE-approver')).toContain('disabled=""')
  })

  it('shows the request to an Approver who did not ask, with Confirm and Not now', () => {
    const html = render({ me: BOB, tab: 'people', confirmations: approverOnly(confirmationsBob) })
    const dave = rowOf(html, 'Dave')
    expect(text(dave)).toContain('Approver: waiting for another Approver to confirm')
    expect(buttonsIn(dave)).toEqual(['Not now for Dave', 'Confirm Dave as an Approver'])
  })

  it('tells an Operator who is not an Approver that it waits for one', () => {
    const forCarol = approverOnly(confirmationsAlice).map((entry) => ({ ...entry, why_not: 'not_an_approver' as const }))
    const dave = rowOf(render({ me: CAROL, tab: 'people', confirmations: forCarol }), 'Dave')
    expect(text(dave)).toContain('Asked by Alice. Waiting for an Approver to confirm.')
    expect(buttonsIn(dave)).toEqual([])
  })

  it('shows a confirmed Approver as an Approver, with nothing waiting', () => {
    const dave = rowOf(render({ tab: 'people', people: CONFIRMED }), 'Dave')
    expect(boxOf(dave, 'person-per_01JD4VE-approver')).toContain('checked=""')
    expect(boxOf(dave, 'person-per_01JD4VE-approver')).not.toContain('disabled')
    expect(text(dave)).not.toContain('waiting for another Approver')
  })

  it('shows someone an Approver said not now to as not an Approver, with nothing waiting', () => {
    const dave = rowOf(render({ tab: 'people', people: NOT_NOW }), 'Dave')
    expect(boxOf(dave, 'person-per_01JD4VE-approver')).not.toContain('checked')
    expect(text(dave)).not.toContain('waiting for another Approver')
  })

  it('lets an Operator add a person and tick roles', () => {
    const html = render({ tab: 'people' })
    const main = text(html)
    expect(main).toContain('Add a person')
    expect(html).toMatch(/<label for="add-email">Work email<\/label>/)
    expect(html).toMatch(/<label for="add-name">Name<\/label>/)
    expect(checkboxes(html).filter((box) => box.includes('disabled'))).toEqual([checkboxes(html).find((box) => box.includes('per_01JD4VE-approver'))])
    expect(buttonsIn(html)).toContain('Add')
  })

  it('is read-only for an Approver who is not an Operator, and says only Operators change settings', () => {
    const html = render({ me: BOB, tab: 'people', people: CONFIRMED })
    expect(text(html)).toContain(ONLY_OPERATORS_WORDS)
    const boxes = checkboxes(html)
    expect(boxes.length).toBe(PEOPLE.length * 2)
    expect(boxes.every((box) => box.includes('disabled=""'))).toBe(true)
    expect(html).not.toContain('<form')
    expect(buttonsIn(html).filter((name) => !['AI model', 'People and roles'].includes(name))).toEqual([])
  })

  it('explains the rules, two Approvers and one Operator among them', () => {
    const main = text(render({ tab: 'people' }))
    expect(main).toContain('Making someone an Approver needs another Approver to confirm it.')
    expect(main).toContain('At least 2 people are Approvers, so nobody has to approve their own work.')
    expect(main).toContain('At least 1 person is an Operator, so someone can always change settings.')
  })

  it('keeps a history that names who asked and who decided', () => {
    const main = text(render({ tab: 'people' }))
    expect(main).toContain('Change history (4)')
    expect(main).toContain('Bob confirmed Dave as an Approver, as Alice asked.')
    expect(main).toContain('Asked by Alice, decided by Bob.')
  })

  it('never uses the retired names', () => {
    for (const html of [render(), render({ tab: 'people' }), render({ me: BOB, tab: 'people' })]) {
      expect(text(html)).not.toMatch(/room lead|release checker|use case/i)
    }
  })
})
