import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import versioned from '../../../../contracts/fixtures/builder/use-case.versioned.json'
import edit from '../../../../contracts/fixtures/planner/answer.edit.json'
import editCant from '../../../../contracts/fixtures/planner/answer.edit.cant.json'
import editChoices from '../../../../contracts/fixtures/planner/answer.edit.choices.json'
import editClash from '../../../../contracts/fixtures/planner/answer.edit.clash.json'
import editHour from '../../../../contracts/fixtures/planner/answer.edit.hour.json'
import editHowOften from '../../../../contracts/fixtures/planner/answer.edit.how_often.json'
import editMissing from '../../../../contracts/fixtures/planner/answer.edit.missing.json'
import editUnclear from '../../../../contracts/fixtures/planner/answer.edit.unclear.json'
import editWatchlist from '../../../../contracts/fixtures/planner/answer.edit.watchlist.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import type { ApiClient } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { keys } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { EditReply, Me, UseCaseView, VersionView, WatchlistView } from '../../api/types'
import { chatScheduleOptions, undoOptions } from '../../api/workflowQueries'
import type { Page } from './AnswerCards'
import { CardMemoryContext, newCardMemory, type EditKept } from './cardMemory'
import { editView, NO_PICKS, openSay, publishedVersion } from './edit'
import { EditCard } from './EditCard'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const NOW = new Date('2026-11-05T15:00:00+08:00')
const PAGE: Page = { ask: () => undefined, edit: () => undefined }
const EDIT = edit as EditReply
const MONDAY_8 = { day: 'monday', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } as const
const WEEKDAYS_8 = { ...MONDAY_8, day: 'weekdays' } as const
const MORNING: UseCaseView = { ...(versioned as UseCaseView), use_case_id: 'uc_01JB8', name: 'Morning new-ticket check', version: 2, schedule: MONDAY_8, next_run_at: '2026-11-09T00:00:00Z' }
const WATCHLIST = statuses as WatchlistView
const SAVED: EditKept = { picks: { useCaseId: null, day: null, at: null }, phase: { kind: 'saved', target: { use_case_id: 'uc_01JB8', name: 'Morning new-ticket check', watchlist: false, before: { day: 'weekdays', at: '08:00' }, after: { day: 'monday', at: '08:00' } }, after: { day: 'monday', at: '08:00' }, version: 2 } }

const version = (n: number, via: VersionView['via']): VersionView => ({ version: n, at: '2026-11-05T01:10:00Z', by: 'alice', via, change: null, undid: null, running: false })

interface Drawn {
  readonly typed?: string
  readonly kept?: EditKept
  readonly useCase?: UseCaseView
  readonly versions?: readonly VersionView[]
  readonly about?: string | null
}

function draw(reply: EditReply, { typed = 'make the morning check run on Mondays only', kept, useCase = { ...MORNING, version: 1, schedule: WEEKDAYS_8 }, versions, about = null }: Drawn = {}): string {
  const session = createDevSession({ getItem: () => ALICE.id, setItem: () => undefined })
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], ALICE)
  queryClient.setQueryData(keys.watchlist(scope), WATCHLIST)
  queryClient.setQueryData(keys.useCase(scope, useCase.use_case_id), useCase)
  if (versions) queryClient.setQueryData(keys.versions(scope, useCase.use_case_id, useCase.version), versions)
  const memory = newCardMemory()
  if (kept) memory.edit.keep(kept)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <CardMemoryContext.Provider value={memory}>
            <EditCard reply={reply} typed={typed} page={PAGE} say={() => undefined} now={NOW} about={about} />
          </CardMemoryContext.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))
const primaries = (html: string) => (html.match(/class="[^"]*_primary_[^"]*"/g) ?? []).length
const sentence = (html: string) => text(/<p[^>]*id="[^"]*-sentence"[^>]*>([\s\S]*?)<\/p>/.exec(html)?.[1] ?? '')

describe('the edit card while it proposes a change', () => {
  it('shows only what changes, before and after, with Save change as the one primary and Never mind', () => {
    const html = draw(EDIT)
    expect(sentence(html)).toBe('Here’s the change. Nothing changes until you save it.')
    expect(html).toMatch(/<h3 id="[^"]*-heading" tabindex="-1">Change Morning new-ticket check<\/h3>/)
    expect(text(html)).toContain('When it runs Before Every weekday at 8:00 After Every Monday at 8:00')
    expect(buttons(html)).toEqual(['Save change', 'Never mind'])
    expect(primaries(html)).toBe(1)
  })

  it('never guesses a time: “at 9” asks 9:00 or 21:00 before Save, and “at 12” asks 0:00 or 12:00', () => {
    const html = draw(editHour as EditReply)
    expect(text(html)).toContain('Question: When At 9:00 or 21:00?')
    expect(buttons(html)).toEqual(['9:00', '21:00', 'Save change', 'Never mind'])
    expect(text(html)).toContain('After Choose a time')
    expect(text(draw({ ...(editHour as EditReply), hour: 12 }))).toContain('At 0:00 or 12:00?')
  })

  it('asks the time when it couldn’t read it, with Another time, and keeps the words it didn’t follow as a cross', () => {
    const html = draw(editUnclear as EditReply)
    expect(sentence(html)).toBe('Here’s the change, but I can’t do every part of it.')
    expect(text(html)).toContain('Question: When What time should it run?')
    expect(buttons(html)).toEqual(['8:00', '9:00', '13:00', '17:00', 'Another time', 'Save change', 'Never mind'])
    expect(text(html)).toContain('Can’t do: “in the afternoon” I didn’t follow this part.')
  })

  it('holds Save for two days, with the cross, the reason, and no button that can’t work', () => {
    const html = draw(editClash as EditReply)
    expect(text(html)).toContain('Can’t do: “Mondays and Thursdays” I can only set one day.')
    expect(text(html)).toContain('Ask again without the part with a cross.')
    expect(buttons(html)).toEqual(['Never mind'])
    expect(text(html)).toContain('After Unchanged')
    expect(primaries(html)).toBe(0)
  })

  it('asks which workflow when the words could mean several, and saves nothing until one is picked', () => {
    const html = draw(editChoices as EditReply)
    expect(sentence(html)).toBe('Which workflow should I change?')
    expect(text(html)).toContain('Question: Workflow Which workflow?')
    expect(buttons(html)).toEqual(['Morning new-ticket check', 'Weekly closed-ticket summary'])
  })

  it('reads “it” as the workflow the answer before was about, names it on the card, and lets her pick another', () => {
    const html = draw(editChoices as EditReply, { about: 'uc_01JB8', typed: 'make it daily' })
    expect(text(html)).toContain('Change Morning new-ticket check')
    expect(text(html)).toContain('Before Every weekday at 8:00 After Every day at 8:00')
    expect(buttons(html)).toEqual(['Pick another workflow', 'Save change', 'Never mind'])
  })

  it('never picks one of several workflows her words fit, even the one talked about before', () => {
    expect(sentence(draw(editChoices as EditReply, { about: 'uc_01JB8', typed: 'make the summary one daily' }))).toBe('Which workflow should I change?')
  })

  it('asks again when a fresh read shows the workflow changed since the answer, so an older card never saves an After worked out from the old schedule', () => {
    const stale = editView(EDIT, NO_PICKS, { day: 'monday', at: '09:00' })
    expect(stale.kind).toBe('stale')
    expect(openSay(EDIT, stale, null)).toBe('Morning new-ticket check changed since I read it, and runs every Monday at 9:00 now. Ask again to change it.')
    expect(editView(EDIT, NO_PICKS, { day: 'weekdays', at: '08:00' }).kind, 'unchanged since').toBe('ready')
    expect(editView(EDIT, NO_PICKS, undefined).kind, 'not read yet').toBe('ready')
  })

  it('names a check that doesn’t exist, says what the watchlist checks, and offers to watch it', () => {
    const html = draw(editMissing as EditReply)
    expect(sentence(html)).toBe('You don’t have a React check. React isn’t on the Software watchlist, which checks software every Monday.')
    expect(buttons(html)).toEqual(['Watch React'])
    expect(html).not.toContain('<section')
    const named = draw({ ...(editMissing as EditReply), missing: 'the morning check', software: null })
    expect(sentence(named)).toBe('You don’t have a workflow called “morning check”.')
    expect(buttons(named)).toEqual([])
  })

  it('answers a change it can’t make with the workflow’s name, keeps the question asked with it, and opens the workflow', () => {
    const html = draw(editCant as EditReply)
    expect(sentence(html)).toBe('From the chat I can only change when Morning new-ticket check runs.')
    expect(text(html)).toContain('Can’t do: “What needs my attention” Ask this on its own, and I’ll answer it.')
    expect(text(html)).not.toContain('“Pause the morning check”')
    expect(buttons(html)).toEqual(['Open Morning new-ticket check'])
    expect(html).toContain('href="/workflows/uc_01JB8"')
  })

  it('says a day left out of a schedule plainly', () => {
    expect(sentence(draw(editHowOften as EditReply))).toBe('I can’t leave days out of a schedule yet.')
  })

  it('says a workflow already runs so, with nothing to save', () => {
    const html = draw({ ...EDIT, after: { day: 'weekdays', at: '08:00' } })
    expect(sentence(html)).toBe('Morning new-ticket check already runs every weekday at 8:00.')
    expect(buttons(html)).toEqual([])
  })

  it('tells her saving the watchlist’s schedule makes her its owner', () => {
    const html = draw(editWatchlist as EditReply, { useCase: { ...MORNING, use_case_id: 'uc_01WL', version: 3, schedule: { ...MONDAY_8, at: '09:00' } } })
    expect(text(html)).toContain('Before Every Monday at 9:00 After Every day at 9:00')
    expect(text(html)).toContain('This changes when all 6 software on the watchlist are checked. Saving makes you the owner of this schedule.')
    expect(buttons(html)).toEqual(['Save change', 'Never mind'])
  })
})

describe('the edit card once she has pressed', () => {
  it('saved: says the version and the next run, with Undo and no primary', () => {
    const html = draw(EDIT, { kept: SAVED, useCase: MORNING })
    expect(sentence(html)).toBe('Saved. Morning new-ticket check runs every Monday at 8:00 now.')
    expect(text(html)).toContain('Saved as version 2. Next run Mon 9 Nov, 8:00.')
    expect(buttons(html)).toEqual(['Undo the change to Morning new-ticket check'])
    expect(primaries(html)).toBe(0)
  })

  it('saved while paused: says it won’t run until she resumes it', () => {
    const html = draw(EDIT, { kept: SAVED, useCase: { ...MORNING, state: 'paused', next_run_at: null } })
    expect(sentence(html)).toBe('Saved. Morning new-ticket check is paused, so it won’t run until you resume it.')
    expect(text(html)).toContain('Saved as version 2. It’s paused, so it won’t run until you resume it.')
  })

  it('changed again on its page since: names where, and takes Undo away so it never throws that change away', () => {
    const html = draw(EDIT, { kept: SAVED, useCase: { ...MORNING, version: 3 }, versions: [version(3, 'page'), version(2, 'chat'), version(1, null)] })
    expect(sentence(html)).toBe('Saved as version 2. Changed again since, on its page.')
    expect(buttons(html)).toEqual([])
    const later = draw(EDIT, { kept: SAVED, useCase: { ...MORNING, version: 3 }, versions: [version(3, 'chat'), version(2, 'chat'), version(1, null)] })
    expect(sentence(later)).toBe('Saved as version 2. Changed again since, in a later answer.')
  })

  it('undone: says the version Undo published and what it runs on again', () => {
    const undone: EditKept = { ...SAVED, phase: { ...SAVED.phase, kind: 'undone', version: 3 } as EditKept['phase'] }
    const html = draw(EDIT, { kept: undone, useCase: { ...MORNING, version: 3, schedule: WEEKDAYS_8 } })
    expect(sentence(html)).toBe('Undone, as version 3. Morning new-ticket check runs every weekday at 8:00 now.')
    expect(text(html)).toContain('Undone, as version 3.')
    expect(buttons(html)).toEqual([])
  })

  it('saved the watchlist’s schedule: keeps no version, so offers no Undo, and says who owns it now', () => {
    const target = { use_case_id: 'uc_01WL', name: 'Keep our software up to date', watchlist: true, before: { day: 'monday' as const, at: '09:00' }, after: { day: 'every_day' as const, at: '09:00' } }
    const kept: EditKept = { picks: SAVED.picks, phase: { kind: 'saved', target, after: { day: 'every_day', at: '09:00' }, version: null } }
    const html = draw(editWatchlist as EditReply, { kept, useCase: { ...MORNING, use_case_id: 'uc_01WL' } })
    expect(sentence(html)).toBe('Saved. Next run Mon 23 Nov, 9:00. You now own this schedule, so you can’t approve its checks.')
    expect(text(html)).toContain('This changed when all 6 software on the watchlist are checked, and made you the owner of this schedule.')
    expect(buttons(html)).toEqual(['Change it on the Software page'])
  })

  it('never mind: changes nothing and says so, with no card', () => {
    const html = draw(EDIT, { kept: { ...SAVED, phase: { kind: 'kept' } } })
    expect(sentence(html)).toBe('No problem. Nothing changed.')
    expect(html).not.toContain('<section')
  })
})

describe('saving and undoing from the card', () => {
  const answered = (data: unknown) => Promise.resolve({ data, response: { ok: true, status: 200 } })

  it('saves through the workflow’s schedule route, marked as a change from the chat, reads who published the newest version, and reads the workflow and the list again', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(keys.useCase('me', 'uc_01JB8'), { ...MORNING, version: 1 })
    queryClient.setQueryData(keys.useCases('me'), [{ ...MORNING, version: 1 }])
    const sent: unknown[] = []
    const client = {
      PUT: (path: string, init: unknown) => (sent.push([path, init]), answered(MORNING)),
      GET: (path: string) => (sent.push([path]), answered({ versions: [version(2, 'chat'), version(1, null)] })),
    } as unknown as ApiClient
    const options = chatScheduleOptions(client, queryClient, 'me')
    const change = { useCaseId: 'uc_01JB8', schedule: { day: 'monday' as const, at: '08:00' } }

    const saved = await options.mutationFn(change)
    options.onSuccess(saved)
    options.onSettled(saved, null, change)

    expect(saved.newest).toEqual(version(2, 'chat'))
    expect(sent).toEqual([
      ['/api/v1/use-cases/{use_case_id}/schedule', { params: { path: { use_case_id: 'uc_01JB8' } }, body: { day: 'monday', at: '08:00', via: 'chat' } }],
      ['/api/v1/use-cases/{use_case_id}/versions'],
    ])
    expect(queryClient.getQueryState(keys.useCase('me', 'uc_01JB8'))?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(keys.useCases('me'))?.isInvalidated).toBe(true)
  })

  it('undoes through the undo route, from the chat', async () => {
    const queryClient = new QueryClient()
    const sent: unknown[] = []
    const client = { POST: (path: string, init: unknown) => (sent.push([path, init]), answered({ ...MORNING, version: 3 })) } as unknown as ApiClient
    await undoOptions(client, queryClient, 'me').mutationFn({ useCaseId: 'uc_01JB8', version: 2 })
    expect(sent).toEqual([['/api/v1/use-cases/{use_case_id}/versions/{version}/undo', { params: { path: { use_case_id: 'uc_01JB8', version: 2 } }, body: { via: 'chat' } }]])
  })

  it('claims a version only when the save published it, so Undo never undoes a version it didn’t make', () => {
    const target = { use_case_id: 'uc_01JB8', name: 'Morning new-ticket check', watchlist: false, before: null, after: null }
    const mine = version(3, 'chat')
    expect(publishedVersion(target, { version: 3 }, mine, 'alice', 2)).toBe(3)
    expect(publishedVersion(target, { version: 3 }, mine, 'alice', undefined), 'before the workflow was read, the newest version still says whose it is').toBe(3)
    expect(publishedVersion(target, { version: 3 }, { ...mine, by: 'carol' }, 'alice', undefined), 'a teammate made the same change first, so nothing was published').toBeNull()
    expect(publishedVersion(target, { version: 3 }, { ...mine, via: 'page' }, 'alice', undefined), 'her own change on the page is not this card’s').toBeNull()
    expect(publishedVersion(target, { version: 1 }, version(1, null), 'alice', 1), 'the same schedule saved again, or a version lost after version 1').toBeNull()
    expect(publishedVersion(target, { version: 3 }, undefined, 'alice', 2), 'the versions could not be read').toBeNull()
    expect(publishedVersion({ ...target, watchlist: true }, { version: 4 }, mine, 'alice', 3), 'the watchlist keeps no versions').toBeNull()
  })
})
