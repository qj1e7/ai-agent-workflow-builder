import { describe, expect, it } from 'vitest'
import newAgent from '../../../../contracts/fixtures/cards/plan.new-agent.json'
import cardList from '../../../../contracts/fixtures/cards/list.json'
import cannotDo from '../../../../contracts/fixtures/cards/plan.cannot-do.json'
import useOne from '../../../../contracts/fixtures/cards/plan.use-one.json'
import rowsAnswer from '../../../../contracts/fixtures/builder/understand.rows.json'
import starters from '../../../../contracts/fixtures/builder/understand.starters.json'
import watchlist from '../../../../contracts/fixtures/builder/understand.watchlist.json'
import { ApiError } from '../../api/client'
import type { CardView, DraftView, PlanOut, RowKind, RowState, ToolId, UnderstandOut } from '../../api/types'
import {
  afterChecking,
  afterReading,
  carryOn,
  changeRow,
  checkedRows,
  checkOf,
  createBody,
  defaultName,
  draftContent,
  dropRow,
  EMPTY_FORM,
  enterWhen,
  nextBlockers,
  partWords,
  taskWithoutSchedule,
  planView,
  readWhen,
  restoreDraft,
  reusedAgents,
  rowBlockers,
  savedCopyOf,
  scheduleOf,
  textProblem,
  turnOn,
  valueOf,
  valueProblem,
  whenProblems,
  whenWords,
  type Form,
  type PlanAgent,
  type TurnOnCalls,
} from './draft'

const FOLLOW_UP = 'Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
const ROWS = rowsAnswer as UnderstandOut
const NEW_AGENT = newAgent as PlanOut
const USE_ONE = useOne as PlanOut
const CANNOT = cannotDo as PlanOut
const TEAMS: UnderstandOut = {
  answer: 'rows',
  rows: [
    { kind: 'schedule', text: '', state: 'missing', note: 'You didn’t say when it runs.' },
    { kind: 'look_for', text: 'Tickets with no update for 14 days', state: 'changed', note: 'You said “stale”, so I used 14 days without an update.' },
    { kind: 'do', text: 'Write a short summary', state: 'understood', note: null },
    { kind: 'where', text: 'Post it in Teams', state: 'cant_do', note: 'I can’t post in Teams yet.' },
  ],
}
const CLEAN_DRAFT: PlanOut = {
  decision: 'new_agent',
  draft: {
    name: 'Stale bug follow-up',
    purpose: 'Lists stale bug tickets in one new ticket.',
    good_for: [],
    inputs: [{ name: 'Jira project', kind: 'jira_project', what: 'Where to look and write.', example: 'ABC' }],
    blocks: [
      { say: 'Find bug tickets with no update for 10 days.', tool: 'jira.search' },
      { say: 'Propose one ticket that lists them.', tool: 'jira.create_ticket' },
    ],
    approvals: [{ tool: 'jira.create_ticket', approvers: 1 }],
  },
  approvals: [{ tool: 'jira.create_ticket', approvers: 1 }],
  problems: [],
  reason: 'No saved agent does this.',
  missing_tools: [],
  questions: [],
}

const read = (answer: UnderstandOut, text = FOLLOW_UP): Form => afterReading({ ...EMPTY_FORM, text }, answer)
const readTeams = (): Form => read(TEAMS, 'Post a summary of stale tickets in Teams')
const KINDS: readonly RowKind[] = ['schedule', 'look_for', 'do', 'where']
const partRead = (kind: RowKind, text: string, state: RowState, note: string | null = null): UnderstandOut => ({
  answer: 'rows',
  rows: KINDS.map((each) => (each === kind ? { kind, text, state, note } : { kind: each, text: '', state: 'missing', note: 'I couldn’t tell from your words.' })),
})
const NOT_CHECKED = 'I couldn’t check your new words just now. Change them to try again.'
const CAN = 'I can only read Jira tickets, sum up what I find, check software for new releases, and create a Jira ticket after a yes.'
const fixed = (form: Form, index: number, text: string): Form => {
  const kind = form.rows[index]?.kind ?? 'where'
  return afterChecking(changeRow(form, index, text), { kind, text }, partRead(kind, text, 'understood'))
}
const agentOf = (answer: PlanOut, form: Form): PlanAgent => {
  const view = planView(answer, form.rows)
  if (view.kind !== 'agents') throw new Error(`no agents in ${view.kind}`)
  const [first] = view.agents
  if (!first) throw new Error('no agent')
  return first
}

describe('step 1, describe it', () => {
  it('asks for some words, and at most 2,000 characters', () => {
    expect(textProblem('   ')).toBe('Write what should happen first.')
    expect(textProblem('x'.repeat(2001))).toBe('Keep it to 2,000 characters.')
    expect(textProblem(FOLLOW_UP)).toBeNull()
  })

  it('opens step 2 with the Planner’s rows', () => {
    const form = read(ROWS)
    expect(form.step).toBe(2)
    expect(form.rows.map((row) => [row.kind, row.text, row.state])).toEqual([
      ['schedule', 'Every weekday at 3pm', 'understood'],
      ['look_for', 'Bug tickets in MOCK with no update for 10 days', 'understood'],
      ['do', 'Create one follow-up ticket that lists them', 'understood'],
      ['where', 'Jira project MOCK', 'understood'],
    ])
    expect(form.redirect).toBeNull()
  })

  it('opens step 2 at the Software watchlist for a release task, with the word that made the Planner think so', () => {
    const form = read(watchlist as UnderstandOut, 'Tell me when LangGraph has a new release')
    expect(form.step).toBe(2)
    expect(form.rows).toEqual([])
    expect(form.redirect).toMatchObject({ word: 'release', software: 'LangGraph' })
  })

  it('stays on step 1 when the Planner could not read the task, and says why', () => {
    const form = read(starters as UnderstandOut)
    expect(form.step).toBe(1)
    expect(form.plannerSaid).toBe((starters as { message: string }).message)
    expect(form.text).toBe(FOLLOW_UP)
  })
})

describe('step 2, check what I understood', () => {
  it('lets four understood rows through', () => {
    expect(rowBlockers(read(ROWS).rows)).toEqual([])
  })

  it('stops at a missing schedule and at a part it can’t do, and says what opens Next', () => {
    const form = read(TEAMS, 'Post a summary of stale tickets in Teams')
    expect(rowBlockers(form.rows)).toEqual([
      { index: 0, words: 'you say when it runs' },
      { index: 3, words: 'you change what I can’t do' },
    ])
    expect(nextBlockers(form, null).words).toBe('Next opens when you say when it runs and you change what I can’t do.')
  })

  it('takes a fixed row as changed by you once the Planner can do it, and an emptied one as missing again', () => {
    const changed = fixed(read(ROWS), 1, 'Bug tickets in MOCK with no update for 14 days')
    expect(changed.rows[1]).toMatchObject({ text: 'Bug tickets in MOCK with no update for 14 days', state: 'edited', note: null })
    expect(changed.rows[1]?.planner?.text).toBe('Bug tickets in MOCK with no update for 10 days')
    expect(changeRow(changed, 1, 'Bug tickets in MOCK with no update for 10 days').rows[1]?.state).toBe('understood')
    expect(changeRow(changed, 1, '  ').rows[1]).toMatchObject({ text: '', state: 'missing' })
  })

  it('opens Next once the missing row is filled in and the Planner can do both changed parts', () => {
    const form = fixed(fixed(readTeams(), 0, 'Every Monday at 9am'), 3, 'Jira project MOCK')
    expect(rowBlockers(form.rows)).toEqual([])
  })

  it('sends a changed can’t-do part back to the Planner as that part, and keeps Next off while it checks', () => {
    const form = changeRow(readTeams(), 3, 'Post it in the team’s Teams channel')
    expect(form.rows[3]).toMatchObject({ text: 'Post it in the team’s Teams channel', state: 'checking', note: null })
    expect(form.rows.filter((row) => row.state === 'checking').map(partWords)).toEqual(['Where it goes: Post it in the team’s Teams channel'])
    expect(nextBlockers(form, null).words).toBe('Next opens when you say when it runs and I’ve checked your new words.')
    expect(changeRow(form, 3, 'Post it in Teams').rows[3]).toMatchObject({ text: 'Post it in Teams', state: 'cant_do', note: 'I can’t post in Teams yet.', planner: null })
  })

  it('clears a changed can’t-do part only when the Planner reads the new words as something it can do', () => {
    const cleared = afterChecking(changeRow(readTeams(), 3, 'Jira project MOCK'), { kind: 'where', text: 'Jira project MOCK' }, partRead('where', 'Jira project MOCK', 'understood'))
    expect(cleared.rows[3]).toMatchObject({ text: 'Jira project MOCK', state: 'edited', note: null })
    expect(cleared.rows[3]?.planner?.text).toBe('Post it in Teams')
    const words = 'Post it in the team’s Teams channel'
    const still = afterChecking(changeRow(readTeams(), 3, words), { kind: 'where', text: words }, partRead('where', words, 'cant_do', 'I can’t post it in the team’s Teams channel yet.'))
    expect(still.rows[3]).toMatchObject({ text: words, state: 'cant_do', note: 'I can’t post it in the team’s Teams channel yet.' })
    expect(rowBlockers(still.rows)).toContainEqual({ index: 3, words: 'you change what I can’t do' })
  })

  it('keeps the part red when the Planner could not check the new words, and drops an answer for words changed since', () => {
    const checking = changeRow(readTeams(), 3, 'Jira project MOCK')
    const part = { kind: 'where', text: 'Jira project MOCK' } as const
    expect(afterChecking(checking, part, null).rows[3]).toMatchObject({ state: 'cant_do', note: NOT_CHECKED })
    expect(afterChecking(checking, part, starters as UnderstandOut).rows[3]).toMatchObject({ state: 'cant_do', note: NOT_CHECKED })
    expect(afterChecking(checking, part, watchlist as UnderstandOut).rows[3]).toMatchObject({ state: 'cant_do', note: (watchlist as { note: string }).note })
    const changedAgain = changeRow(checking, 3, 'Jira project ABC')
    expect(afterChecking(changedAgain, part, partRead('where', 'Jira project MOCK', 'understood'))).toEqual(changedAgain)
  })

  it('sends “Where it goes” changed to a Teams channel post back to the Planner, and keeps it red when the tools can’t do it', () => {
    const words = 'Post it in the team’s Teams channel'
    const note = `I can't post it in the team’s Teams channel yet. ${CAN}`
    const form = changeRow(read(ROWS), 3, words)
    expect(form.rows[3]).toMatchObject({ text: words, state: 'checking', note: null })
    expect(form.rows.filter((row) => row.state === 'checking').map(partWords)).toEqual([`Where it goes: ${words}`])
    expect(nextBlockers(form, null).words).toBe('Next opens when I’ve checked your new words.')
    const checked = afterChecking(form, { kind: 'where', text: words }, partRead('where', words, 'cant_do', note))
    expect(checked.rows[3]).toMatchObject({ text: words, state: 'cant_do', note })
    expect(nextBlockers(checked, null).words).toBe('Next opens when you change what I can’t do.')
    expect(checkedRows({ ...enterWhen(checked), step: 4 }).map((row) => row.words)).not.toContain(`Where it goes: ${words}. You changed this.`)
  })

  it('sends an empty “Does” filled in with a Teams summary back to the Planner, and keeps it red when the tools can’t do it', () => {
    const words = 'Post a summary of them in the Teams channel'
    const note = `I can't post a summary of them in the Teams channel yet. ${CAN}`
    const noDoes = read({ answer: 'rows', rows: (ROWS.answer === 'rows' ? ROWS.rows : []).map((row) => (row.kind === 'do' ? { ...row, text: '', state: 'missing', note: 'I couldn’t tell from your words.' } : row)) })
    expect(noDoes.rows[2]).toMatchObject({ kind: 'do', state: 'missing' })
    const form = changeRow(noDoes, 2, words)
    expect(form.rows[2]).toMatchObject({ text: words, state: 'checking' })
    expect(form.rows.filter((row) => row.state === 'checking').map(partWords)).toEqual([`Does: ${words}`])
    expect(taskWithoutSchedule(form.rows)).toContain(words)
    expect(nextBlockers(form, null).words).toBe('Next opens when I’ve checked your new words.')
    const checked = afterChecking(form, { kind: 'do', text: words }, partRead('do', words, 'cant_do', note))
    expect(checked.rows[2]).toMatchObject({ state: 'cant_do', note })
    expect(rowBlockers(checked.rows)).toEqual([{ index: 2, words: 'you change what I can’t do' }])
  })

  it('checks a part that was understood too, and shows it as changed by you once the Planner can do it', () => {
    const form = changeRow(read(ROWS), 3, 'Jira project ABC')
    expect(form.rows[3]).toMatchObject({ text: 'Jira project ABC', state: 'checking' })
    expect(afterChecking(form, { kind: 'where', text: 'Jira project ABC' }, partRead('where', 'Jira project ABC', 'understood')).rows[3]).toMatchObject({ state: 'edited', note: null })
  })

  const carried = (): Form => carryOn(read(watchlist as UnderstandOut, 'Tell me when LangGraph has a new release'))

  it('checks each part filled in after carrying on, telling the Planner the Operator chose a new workflow, and takes a release part it can do', () => {
    const words = 'New releases of langchain-ai/langgraph on GitHub'
    const form = changeRow(carried(), 1, words)
    expect(form.rows[1]).toMatchObject({ text: words, state: 'checking' })
    expect(checkOf(form, { kind: 'look_for', text: words })).toEqual({ text: `Looks for: ${words}`, carriedOn: true })
    expect(afterChecking(form, { kind: 'look_for', text: words }, partRead('look_for', words, 'understood')).rows[1]).toMatchObject({ state: 'edited', note: null })
    expect(checkOf(changeRow(read(ROWS), 3, 'Jira project ABC'), { kind: 'where', text: 'Jira project ABC' })).toEqual({ text: 'Where it goes: Jira project ABC', carriedOn: false })
  })

  it.each([
    [3, 'where', 'Post the release notes in the team’s Teams channel', 'post the release notes in the team’s Teams channel'],
    [2, 'do', 'Email the upgrade list to the team', 'email the upgrade list to the team'],
  ] as const)('keeps a part filled in after carrying on red when the tools can’t do it: %s, “%s”', (index, kind, words, what) => {
    const form = changeRow(carried(), index, words)
    const part = { kind, text: words }
    expect(checkOf(form, part)).toMatchObject({ carriedOn: true })
    const note = `I can't ${what} yet. ${CAN}`
    expect(afterChecking(form, part, partRead(kind, words, 'cant_do', note)).rows[index]).toMatchObject({ state: 'cant_do', note })
    expect(afterChecking(form, part, watchlist as UnderstandOut).rows[index]).toMatchObject({ state: 'cant_do' })
  })

  it('leaves out a part only when another of its kind stays', () => {
    const split: UnderstandOut = {
      answer: 'rows',
      rows: [
        { kind: 'schedule', text: 'Every Monday at 9am', state: 'understood', note: null },
        { kind: 'look_for', text: 'Bug tickets in MOCK', state: 'understood', note: null },
        { kind: 'do', text: 'Create one ticket that lists them', state: 'understood', note: null },
        { kind: 'do', text: 'Close the old ones', state: 'cant_do', note: 'I can’t close tickets.' },
        { kind: 'where', text: 'Jira project MOCK', state: 'understood', note: null },
      ],
    }
    const form = read(split)
    expect(dropRow(form, 3).rows.map((row) => row.text)).not.toContain('Close the old ones')
    expect(dropRow(form, 1).rows).toHaveLength(5)
  })

  it('carries a release task on as a new workflow with the task kept and the four parts to fill in', () => {
    const form = carryOn(read(watchlist as UnderstandOut, 'Tell me when LangGraph has a new release'))
    expect(form.step).toBe(2)
    expect(form.text).toBe('Tell me when LangGraph has a new release')
    expect(form.redirect).toBeNull()
    expect(form.rows.map((row) => [row.kind, row.state])).toEqual([
      ['schedule', 'missing'],
      ['look_for', 'missing'],
      ['do', 'missing'],
      ['where', 'missing'],
    ])
  })

  it('asks the Planner for a plan with the rows, not the schedule', () => {
    expect(taskWithoutSchedule(read(ROWS).rows)).toBe('Find bug tickets in MOCK with no update for 10 days. Create one follow-up ticket that lists them. Where it goes: Jira project MOCK.')
  })
})

describe('the plan in step 2', () => {
  it('fills a drafted agent’s Jira project from the rows', () => {
    const form = read(ROWS)
    const agent = agentOf(CLEAN_DRAFT, form)
    expect(agent).toMatchObject({ card: { kind: 'drafted' }, name: 'Stale bug follow-up' })
    expect(valueOf(form, agent, 'Jira project')).toBe('MOCK')
    expect(nextBlockers(form, planView(CLEAN_DRAFT, form.rows)).words).toBe('')
  })

  it('takes a saved agent’s values from the Planner and asks for the missing one', () => {
    const form = read(ROWS)
    const agent = agentOf(USE_ONE, form)
    expect(agent.card).toEqual({ kind: 'saved', id: 'crd_version_checker' })
    expect(valueOf(form, agent, 'GitHub repository')).toBe('langchain-ai/langgraph')
    const typed = { ...form, typed: { [`0:Jira project`]: '' } }
    expect(nextBlockers(typed, planView(USE_ONE, typed.rows)).words).toBe('Next opens when you fill in Jira project.')
  })

  it('checks each value by its kind', () => {
    expect(valueProblem('jira_project', 'mock')).toBeNull()
    expect(valueProblem('jira_project', 'MO CK')).toBe('Write the project key, such as MOCK.')
    expect(valueProblem('github_repo', 'https://github.com/langchain-ai/langgraph')).toBeNull()
    expect(valueProblem('github_repo', 'langgraph')).toBe('Write it as owner/name, such as langchain-ai/langgraph.')
    expect(valueProblem('text', '')).toBe('Fill this in.')
  })

  it('stops at a drafted agent with problems, and at a task the Planner can’t do', () => {
    const form = read(ROWS)
    const drafted = planView(NEW_AGENT, form.rows)
    expect(drafted.kind === 'agents' && drafted.problems).toEqual([
      'Add a Jira project detail, so the agent knows which project it may read.',
      'Forge is an old name that confused the sponsor. Use plain words.',
    ])
    expect(nextBlockers(form, drafted).words).toBe('Next opens when you change your words so the new agent has no problems.')
    const cannot = planView(CANNOT, form.rows)
    expect(cannot).toMatchObject({ kind: 'cannot', reason: 'Booking a meeting room needs a calendar, and the platform has no calendar tool.' })
    expect(nextBlockers(form, cannot).words).toBe('Next opens when you change your words to something I can do.')
  })

  it('keeps Next off while the plan leaves a part out, even once the Planner clears the changed part', () => {
    const form = { ...fixed(fixed(readTeams(), 0, 'Every Monday at 9am'), 3, 'Jira project MOCK'), typed: { '0:Jira project': 'MOCK' } }
    expect(rowBlockers(form.rows)).toEqual([])
    const leftOut: PlanOut = { ...CLEAN_DRAFT, missing_tools: [{ need: 'Post in Teams', why: 'To share the list with the team.' }] }
    expect(nextBlockers(form, planView(leftOut, form.rows)).words).toBe('Next opens when you change your words so nothing is left out.')
  })

  it('waits for the plan before Next opens', () => {
    expect(nextBlockers(read(ROWS), null).words).toBe('Next opens when the plan is ready.')
  })
})

describe('step 3, when it runs', () => {
  it.each([
    ['Every weekday at 3pm', { often: 'weekdays', day: '', at: '15:00' }],
    ['Every Friday at 4pm', { often: 'week', day: 'friday', at: '16:00' }],
    ['Each Monday at 09:30', { often: 'week', day: 'monday', at: '09:30' }],
    ['Daily at noon', { often: 'every_day', day: '', at: '12:00' }],
    ['Every Wednesday', { often: 'week', day: 'wednesday', at: '' }],
    ['Monday to Friday at 8.15am', { often: 'weekdays', day: '', at: '08:15' }],
    ['At 7pm', { often: '', day: '', at: '19:00' }],
    ['Fortnightly', { often: '', day: '', at: '' }],
  ])('reads “%s” and never guesses the rest', (text, when) => {
    expect(readWhen(text)).toMatchObject(when)
  })

  it('fills in from the schedule row once, and keeps a choice the Operator made', () => {
    const form = enterWhen(read(ROWS))
    expect(form.when).toMatchObject({ often: 'weekdays', at: '15:00', filledFrom: 'Every weekday at 3pm' })
    const chosen = enterWhen({ ...form, when: { ...form.when, at: '16:00' } })
    expect(chosen.when.at).toBe('16:00')
  })

  it('asks for how often, the day and the time on a five-minute step', () => {
    expect(whenProblems({ often: '', day: '', at: '', filledFrom: null })).toEqual({ often: 'Choose how often it runs.', at: 'Choose a time.' })
    expect(whenProblems({ often: 'week', day: '', at: '09:00', filledFrom: null })).toEqual({ day: 'Choose a day.' })
    expect(whenProblems({ often: 'weekdays', day: '', at: '09:03', filledFrom: null }).at).toBe('Pick a time on a 5-minute step, such as 9:00.')
    expect(whenProblems({ often: 'weekdays', day: '', at: '15:00', filledFrom: null })).toEqual({})
  })

  it('says the schedule and sends the platform its day', () => {
    const weekdays = { often: 'weekdays', day: '', at: '15:00', filledFrom: null } as const
    expect(whenWords(weekdays)).toBe('Every weekday at 15:00')
    expect(scheduleOf(weekdays)).toEqual({ day: 'weekdays', at: '15:00' })
    expect(scheduleOf({ often: 'week', day: 'friday', at: '16:00', filledFrom: null })).toEqual({ day: 'friday', at: '16:00' })
    expect(whenWords({ often: 'every_day', day: '', at: '09:05', filledFrom: null })).toBe('Every day at 9:05')
  })
})

describe('step 4, turn it on', () => {
  const ready = (): Form => {
    const form = enterWhen(fixed(read(ROWS), 1, 'Bug tickets in MOCK with no update for 14 days'))
    return { ...form, step: 4 }
  }

  it('names it after the agents', () => {
    expect(defaultName(planView(CLEAN_DRAFT, ready().rows))).toBe('Stale bug follow-up')
    expect(defaultName(planView(USE_ONE, ready().rows))).toBe('Version checker')
  })

  it('checks each part against the request', () => {
    const form = { ...ready(), when: { ...ready().when, at: '16:00' } }
    expect(checkedRows(form)).toEqual([
      { ok: false, words: 'When: Every weekday at 16:00. You asked for “Every weekday at 3pm”.' },
      { ok: false, words: 'Looks for: Bug tickets in MOCK with no update for 14 days. You changed this.' },
      { ok: true, words: 'Does: Create one follow-up ticket that lists them, as you asked.' },
      { ok: true, words: 'Where it goes: Jira project MOCK, as you asked.' },
    ])
    expect(checkedRows(ready())[0]).toEqual({ ok: true, words: 'When: Every weekday at 15:00, as you asked.' })
  })

  it('sends the name, the rows as the instruction, each agent’s values and the schedule', () => {
    const form = { ...ready(), name: '  Follow up stale bugs ' }
    expect(createBody(form, planView(CLEAN_DRAFT, form.rows), { 0: 'crd_new' })).toEqual({
      name: 'Follow up stale bugs',
      instruction: 'Find bug tickets in MOCK with no update for 14 days. Create one follow-up ticket that lists them. Where it goes: Jira project MOCK.',
      agents: [{ card_id: 'crd_new', values: { 'Jira project': 'MOCK' } }],
      schedule: { day: 'weekdays', at: '15:00' },
    })
    const named = createBody({ ...form, name: '' }, planView(CLEAN_DRAFT, form.rows), { 0: 'crd_new' })
    expect(named.name).toBe('Stale bug follow-up')
  })
})

describe('pressing Turn it on', () => {
  const form = (): Form => ({ ...enterWhen(read(ROWS)), step: 4, name: 'Follow up stale bugs' })

  function fakeCalls(failing: number, saved: string | null = null): { readonly calls: TurnOnCalls; readonly seen: string[] } {
    const seen: string[] = []
    const answer = <T>(said: string, value: T): Promise<T> => {
      seen.push(said)
      return seen.length === failing ? Promise.reject(new ApiError(500, null)) : Promise.resolve(value)
    }
    return {
      seen,
      calls: {
        savedCard: (card) => answer(`look for ${card.name}`, saved),
        saveCard: (card) => answer(`save ${card.name}`, 'crd_new'),
        create: (body) => answer(`create with ${body.agents.map((agent) => agent.card_id).join(', ')}`, { use_case_id: 'uc_new', version: 1 }),
        deleteDraft: (draftId) => answer(`delete draft ${draftId}`, undefined),
      },
    }
  }

  it('saves the new agent, then the workflow with it, and after a failure the next press reuses the saved agent', async () => {
    const { calls, seen } = fakeCalls(3)
    const cards = new Map<string, string>()
    const plan = planView(CLEAN_DRAFT, form().rows)
    await expect(turnOn(form(), plan, 'd1', cards, calls)).rejects.toBeInstanceOf(ApiError)
    expect(seen).toEqual(['look for Stale bug follow-up', 'save Stale bug follow-up', 'create with crd_new'])
    await expect(turnOn(form(), plan, 'd1', cards, calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: false })
    expect(seen).toEqual(['look for Stale bug follow-up', 'save Stale bug follow-up', 'create with crd_new', 'create with crd_new', 'delete draft d1'])
  })

  it('uses the agent the Operator already saved for the same plan, and saves no copy', async () => {
    const { calls, seen } = fakeCalls(0, 'crd_saved')
    await expect(turnOn(form(), planView(CLEAN_DRAFT, form().rows), null, new Map(), calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: false })
    expect(seen).toEqual(['look for Stale bug follow-up', 'create with crd_saved'])
  })

  it('finds only the Operator’s own saved agent with the same name, purpose, inputs and steps', () => {
    const drafted = CLEAN_DRAFT.decision === 'new_agent' ? CLEAN_DRAFT.draft : null
    if (drafted === null) throw new Error('no draft')
    const starter = (cardList as { cards: CardView[] }).cards[0]
    if (!starter) throw new Error('no card')
    const copy = (card_id: string, owner: string, change: Partial<CardView> = {}): CardView => ({
      ...starter,
      card_id,
      owner,
      starter: false,
      name: drafted.name,
      purpose: drafted.purpose,
      good_for: drafted.good_for ?? [],
      inputs: (drafted.inputs ?? []).map((input) => ({ ...input, kind: 'jira_project' })),
      blocks: (drafted.blocks ?? []).map((block) => ({ say: block.say, tool: (block.tool ?? null) as ToolId | null })),
      ...change,
    })
    const other = copy('crd_bob', 'bob')
    const changed = copy('crd_changed', 'alice', { blocks: [{ say: 'Find bug tickets.', tool: 'jira.search' }] })
    expect(savedCopyOf([starter, other, changed], 'alice', drafted)).toBeNull()
    expect(savedCopyOf([starter, other, changed, copy('crd_mine', 'alice')], 'alice', drafted)).toBe('crd_mine')
  })

  it('knows which drafted agents the Operator already saved, so the words say the workflow reuses them', () => {
    const drafted = CLEAN_DRAFT.decision === 'new_agent' ? CLEAN_DRAFT.draft : null
    const starter = (cardList as { cards: CardView[] }).cards[0]
    if (drafted === null || !starter) throw new Error('no draft or card')
    const mine: CardView = {
      ...starter,
      card_id: 'crd_mine',
      owner: 'alice',
      starter: false,
      name: drafted.name,
      purpose: drafted.purpose,
      good_for: drafted.good_for ?? [],
      inputs: (drafted.inputs ?? []).map((input) => ({ ...input, kind: 'jira_project' })),
      blocks: (drafted.blocks ?? []).map((block) => ({ say: block.say, tool: (block.tool ?? null) as ToolId | null })),
    }
    const plan = planView(CLEAN_DRAFT, form().rows)
    expect([...(reusedAgents(plan, [starter, mine], 'alice') ?? [])]).toEqual([0])
    expect([...(reusedAgents(plan, [starter, mine], 'bob') ?? [])]).toEqual([])
    expect(reusedAgents(plan, undefined, 'alice')).toBeNull()
    expect(reusedAgents(plan, [starter, mine], undefined)).toBeNull()
    expect([...(reusedAgents(planView(USE_ONE, form().rows), [starter, mine], 'alice') ?? [])]).toEqual([])
  })

  it('saves nothing new for a saved agent, and has no draft to delete for a workflow never saved as one', async () => {
    const { calls, seen } = fakeCalls(0)
    await expect(turnOn(form(), planView(USE_ONE, form().rows), null, new Map(), calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: false })
    expect(seen).toEqual(['create with crd_version_checker'])
  })

  it('still turns it on when the draft cannot be deleted, and says the draft is kept', async () => {
    const { calls, seen } = fakeCalls(4)
    await expect(turnOn(form(), planView(CLEAN_DRAFT, form().rows), 'd1', new Map(), calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: true })
    expect(seen).toEqual(['look for Stale bug follow-up', 'save Stale bug follow-up', 'create with crd_new', 'delete draft d1'])
  })
})

describe('a draft', () => {
  const saved = (step: number, content: Record<string, unknown>): DraftView => ({
    draft_id: 'd1',
    step,
    content: content,
    created_at: '2026-11-03T07:00:00Z',
    saved_at: '2026-11-03T07:00:00Z',
  })

  it('reopens at the step it was saved at, with the same form and plan', () => {
    const form = { ...enterWhen(read(ROWS)), step: 3 as const, typed: { '0:Jira project': 'ABC' } }
    const plan = { task: taskWithoutSchedule(form.rows), answer: CLEAN_DRAFT }
    const content = JSON.parse(JSON.stringify(draftContent(form, plan))) as Record<string, unknown>
    expect(content['name']).toBe('Stale bug follow-up')
    expect(restoreDraft(saved(3, content))).toEqual({ form, plan })
  })

  it('sends a part changed by you back to the Planner when the draft reopens, at step 2 so Next waits for it', () => {
    const form = { ...enterWhen(fixed(read(ROWS), 1, 'Bug tickets in MOCK with no update for 14 days')), step: 3 as const }
    expect(form.rows[1]?.state).toBe('edited')
    const content = JSON.parse(JSON.stringify(draftContent(form, null))) as Record<string, unknown>
    const reopened = restoreDraft(saved(3, content)).form
    expect(reopened.step).toBe(2)
    expect(reopened.rows[1]).toMatchObject({ text: 'Bug tickets in MOCK with no update for 14 days', state: 'checking', note: null })
    expect(reopened.rows[1]?.planner?.text).toBe('Bug tickets in MOCK with no update for 10 days')
    expect(reopened.rows.filter((row) => row.state === 'checking')).toHaveLength(1)
    expect(nextBlockers(reopened, null).words).toBe('Next opens when I’ve checked your new words.')
  })

  it('keeps that the Operator carried on past the watchlist when the draft reopens', () => {
    const content = JSON.parse(JSON.stringify(draftContent(carryOn(read(watchlist as UnderstandOut, 'Tell me when LangGraph has a new release')), null))) as Record<string, unknown>
    expect(restoreDraft(saved(2, content)).form.carriedOn).toBe(true)
  })

  it('saves a part still being checked as one I can’t do yet, so the reopened draft asks again', () => {
    const checking = changeRow(readTeams(), 3, 'Jira project MOCK')
    const content = JSON.parse(JSON.stringify(draftContent(checking, null))) as Record<string, unknown>
    expect(restoreDraft(saved(2, content)).form.rows[3]).toMatchObject({ text: 'Jira project MOCK', state: 'cant_do', note: NOT_CHECKED })
  })

  it('keeps the name at the top, from what was typed, the plan, or the task', () => {
    const form = read(ROWS)
    expect(draftContent({ ...form, name: 'Mine' }, null)['name']).toBe('Mine')
    expect(draftContent({ ...EMPTY_FORM, text: FOLLOW_UP }, null)['name']).toBe('Every weekday at 3pm, find bug tickets in MOCK with no…')
    expect(draftContent(EMPTY_FORM, null)['name']).toBeNull()
  })

  it('reopens a draft it cannot read at step 1 with whatever task it holds', () => {
    expect(restoreDraft(saved(2, { intent: 'Every Wednesday, find tickets', name: 'Nudge stale tickets' }))).toEqual({
      form: { ...EMPTY_FORM, text: 'Every Wednesday, find tickets' },
      plan: null,
    })
    expect(restoreDraft(saved(3, { form: { step: 'x' } }))?.form).toEqual(EMPTY_FORM)
  })
})
