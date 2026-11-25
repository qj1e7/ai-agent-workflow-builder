import { describe, expect, it } from 'vitest'
import newAgent from '../../../../contracts/fixtures/cards/plan.new-agent.json'
import cardList from '../../../../contracts/fixtures/cards/list.json'
import cannotDo from '../../../../contracts/fixtures/cards/plan.cannot-do.json'
import useOne from '../../../../contracts/fixtures/cards/plan.use-one.json'
import setupCardAnswer from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import partAnswer from '../../../../contracts/fixtures/planner/answer.part.json'
import clashAnswer from '../../../../contracts/fixtures/planner/answer.setup_card.clash.json'
import crossAnswer from '../../../../contracts/fixtures/planner/answer.setup_card.cross.json'
import checkCant from '../../../../contracts/fixtures/planner/check-part.cant.json'
import answered24Hour from '../../../../contracts/fixtures/agent/planner-answered-card-24-hour.json'
import { ApiError } from '../../api/client'
import type { CardToolId, CardView, DraftView, PartReply, PartView, PlanOut, RowKind, RowState, SetupCardReply } from '../../api/types'
import {
  afterPartCheck,
  andList,
  answerWhen,
  cardFrom,
  chooseProject,
  cardBlockers,
  nextQuestion,
  answerFirst,
  openParts,
  questionsOf,
  softwareOf,
  repoMissing,
  chooseRepo,
  effectiveRepo,
  REPO_CHOICE,
  openPartsFor,
  REPO_FOUND,
  JIRA_CHOICE,
  hasTicketWrite,
  setUpWords,
  secondName,
  timeWords,
  cardPhase,
  isQuestion,
  leftWords,
  savedLeft,
  setupLeft,
  whenSaid,
  changeRow,
  checkedRows,
  createBody,
  defaultName,
  draftContent,
  draftWrites,
  dropRow,
  EMPTY_FORM,
  ROW_LABEL,
  enterWhen,
  nextBlockers,
  taskWithoutSchedule,
  planView,
  readWhen,
  restoreDraft,
  reusedAgents,
  rowBlockers,
  savedCopyOf,
  scheduleOf,
  setUp,
  valueOf,
  valueProblem,
  whenProblems,
  whenWords,
  type Form,
  type PlanView,
  type PartResult,
  type PlanAgent,
  type RepoFind,
  type Row,
  type SetUpCalls,
} from './card'

const FOLLOW_UP = 'Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
interface Answered {
  readonly rows: readonly { readonly kind: RowKind; readonly text: string; readonly state: RowState; readonly note: string | null }[]
}
const ROWS: Answered = {
  rows: [
    { kind: 'schedule', text: 'Every weekday at 3pm', state: 'understood', note: null },
    { kind: 'look_for', text: 'Bug tickets in MOCK with no update for 10 days', state: 'understood', note: null },
    { kind: 'do', text: 'Create one follow-up ticket that lists them', state: 'understood', note: null },
    { kind: 'where', text: 'Jira project MOCK', state: 'understood', note: null },
  ],
}
const NEW_AGENT = newAgent as PlanOut
const TICKET_PLAN = planView({ ...(NEW_AGENT as object), project: null } as PlanOut, [])
const USE_ONE = useOne as PlanOut
const CANNOT = cannotDo as PlanOut
const TEAMS: Answered = {
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

const read = (answer: Answered, text = FOLLOW_UP): Form => ({ ...EMPTY_FORM, text, step: 2, rows: answer.rows.map((row) => ({ ...row, planner: null })) })
const partWords = (part: Pick<Row, 'kind' | 'text'>) => `${ROW_LABEL[part.kind]}: ${part.text}`
const readTeams = (): Form => read(TEAMS, 'Post a summary of stale tickets in Teams')
const partRead = (_kind: RowKind, _text: string, state: RowState, note: string | null = null): PartResult =>
  state === 'understood' ? { state: 'fits' } : { state: 'cant_do', ...(note === null ? {} : { note }) }
const NOT_CHECKED = 'I couldn’t check your new words just now. Change them to try again.'
const CAN = 'I can only read Jira tickets, sum up what I find, check software for new releases, create a Jira ticket after a yes, and ask Approvers for a yes in Teams.'
const fixed = (form: Form, index: number, text: string): Form => {
  const kind = form.rows[index]?.kind ?? 'where'
  return afterPartCheck(changeRow(form, index, text), { kind, text }, partRead(kind, text, 'understood'))
}
const agentOf = (answer: PlanOut, form: Form): PlanAgent => {
  const view = planView(answer, form.rows)
  if (view.kind !== 'agents') throw new Error(`no agents in ${view.kind}`)
  const [first] = view.agents
  if (!first) throw new Error('no agent')
  return first
}

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
    const cleared = afterPartCheck(changeRow(readTeams(), 3, 'Jira project MOCK'), { kind: 'where', text: 'Jira project MOCK' }, partRead('where', 'Jira project MOCK', 'understood'))
    expect(cleared.rows[3]).toMatchObject({ text: 'Jira project MOCK', state: 'edited', note: null })
    expect(cleared.rows[3]?.planner?.text).toBe('Post it in Teams')
    const words = 'Post it in the team’s Teams channel'
    const still = afterPartCheck(changeRow(readTeams(), 3, words), { kind: 'where', text: words }, partRead('where', words, 'cant_do', 'I can’t post it in the team’s Teams channel yet.'))
    expect(still.rows[3]).toMatchObject({ text: words, state: 'cant_do', note: 'I can’t post it in the team’s Teams channel yet.' })
    expect(rowBlockers(still.rows)).toContainEqual({ index: 3, words: 'you change what I can’t do' })
  })

  it('keeps the part red when the Planner could not check the new words, and drops an answer for words changed since', () => {
    const checking = changeRow(readTeams(), 3, 'Jira project MOCK')
    const part = { kind: 'where', text: 'Jira project MOCK' } as const
    expect(afterPartCheck(checking, part, null).rows[3]).toMatchObject({ state: 'cant_do', note: NOT_CHECKED })
    const changedAgain = changeRow(checking, 3, 'Jira project ABC')
    expect(afterPartCheck(changedAgain, part, partRead('where', 'Jira project MOCK', 'understood'))).toEqual(changedAgain)
  })

  it('sends “Where it goes” changed to a Teams channel post back to the Planner, and keeps it red when the tools can’t do it', () => {
    const words = 'Post it in the team’s Teams channel'
    const note = `I can't post it in the team’s Teams channel yet. ${CAN}`
    const form = changeRow(read(ROWS), 3, words)
    expect(form.rows[3]).toMatchObject({ text: words, state: 'checking', note: null })
    expect(form.rows.filter((row) => row.state === 'checking').map(partWords)).toEqual([`Where it goes: ${words}`])
    expect(nextBlockers(form, null).words).toBe('Next opens when I’ve checked your new words.')
    const checked = afterPartCheck(form, { kind: 'where', text: words }, partRead('where', words, 'cant_do', note))
    expect(checked.rows[3]).toMatchObject({ text: words, state: 'cant_do', note })
    expect(nextBlockers(checked, null).words).toBe('Next opens when you change what I can’t do.')
    expect(checkedRows({ ...enterWhen(checked), step: 4 }).map((row) => row.words)).not.toContain(`Where it goes: ${words}. You changed this.`)
  })

  it('sends an empty “Does” filled in with a Teams summary back to the Planner, and keeps it red when the tools can’t do it', () => {
    const words = 'Post a summary of them in the Teams channel'
    const note = `I can't post a summary of them in the Teams channel yet. ${CAN}`
    const noDoes = read({ rows: ROWS.rows.map((row) => (row.kind === 'do' ? { ...row, text: '', state: 'missing', note: 'I couldn’t tell from your words.' } : row)) })
    expect(noDoes.rows[2]).toMatchObject({ kind: 'do', state: 'missing' })
    const form = changeRow(noDoes, 2, words)
    expect(form.rows[2]).toMatchObject({ text: words, state: 'checking' })
    expect(form.rows.filter((row) => row.state === 'checking').map(partWords)).toEqual([`Does: ${words}`])
    expect(taskWithoutSchedule(form.rows)).toContain(words)
    expect(nextBlockers(form, null).words).toBe('Next opens when I’ve checked your new words.')
    const checked = afterPartCheck(form, { kind: 'do', text: words }, partRead('do', words, 'cant_do', note))
    expect(checked.rows[2]).toMatchObject({ state: 'cant_do', note })
    expect(rowBlockers(checked.rows)).toEqual([{ index: 2, words: 'you change what I can’t do' }])
  })

  it('checks a part that was understood too, and shows it as changed by you once the Planner can do it', () => {
    const form = changeRow(read(ROWS), 3, 'Jira project ABC')
    expect(form.rows[3]).toMatchObject({ text: 'Jira project ABC', state: 'checking' })
    expect(afterPartCheck(form, { kind: 'where', text: 'Jira project ABC' }, partRead('where', 'Jira project ABC', 'understood')).rows[3]).toMatchObject({ state: 'edited', note: null })
  })

  it('leaves out a part only when another of its kind stays', () => {
    const split: Answered = {
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

  it('asks the Planner for a plan with the rows, not the schedule', () => {
    expect(taskWithoutSchedule(read(ROWS).rows)).toBe('Find bug tickets in MOCK with no update for 10 days. Create one follow-up ticket that lists them. Where it goes: Jira project MOCK.')
  })

  it('plans the card beside a watch with the software’s name as they wrote it', () => {
    const beside: Answered = {
      ...ROWS,
      rows: [
        { kind: 'schedule', text: 'Every Monday', state: 'understood', note: null },
        { kind: 'look_for', text: 'New releases of LangGraph', state: 'understood', note: 'Read from your words "LangGraph".' },
        { kind: 'do', text: 'Create one ticket that lists them', state: 'understood', note: null },
        { kind: 'where', text: 'Jira project OPS', state: 'understood', note: null },
      ],
    }
    expect(taskWithoutSchedule(read(beside).rows)).toBe('Find new releases of LangGraph. Create one ticket that lists them. Where it goes: Jira project OPS.')
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
    expect(valueProblem('jira_project', 'ab_1')).toBeNull()
    expect(valueProblem('jira_project', 'A' + 'B'.repeat(254))).toBeNull()
    expect(valueProblem('jira_project', 'A' + 'B'.repeat(255))).toBe('Write the project key, such as MOCK.')
    expect(valueProblem('jira_project', '_AB')).toBe('Write the project key, such as MOCK.')
    expect(valueProblem('jira_project', 'A')).toBe('Write the project key, such as MOCK.')
    expect(valueProblem('jira_project', 'AB')).toBeNull()
    expect(valueProblem('github_repo', 'https://github.com/langchain-ai/langgraph')).toBeNull()
    expect(valueProblem('github_repo', 'langgraph')).toBe('Write it as owner/name, such as langchain-ai/langgraph.')
    expect(valueProblem('text', '')).toBe('Fill this in.')
  })

  it('stops at a drafted agent with problems, and at a task the Planner can’t do', () => {
    const form = read(ROWS)
    const drafted = planView(NEW_AGENT, form.rows)
    expect(drafted.kind === 'agents' && drafted.problems).toEqual(['Forge is an old name that confused the sponsor. Use plain words.'])
    expect(nextBlockers(form, drafted).words).toBe('Next opens when you change your words so the new agent has no problems.')
    const cannot = planView(CANNOT, form.rows)
    expect(cannot).toMatchObject({ kind: 'cannot', reason: 'Booking a meeting room needs a calendar, and the platform has no calendar tool.' })
    expect(nextBlockers(form, cannot).words).toBe('Next opens when you change your words to something I can do.')
  })

  it('fills the Jira project from the one project the builder read in their words, never the first “in X” of the rows', () => {
    const rows = [...ROWS.rows.slice(0, 3), { kind: 'where' as const, text: 'Jira project OPS', state: 'understood' as const, note: null }]
    const form = cardFrom('x', rows, '')
    const drafted = planView({ ...NEW_AGENT, project: 'OPS' } as PlanOut, form.rows)
    expect(drafted.kind === 'agents' && drafted.agents[0]?.found).toEqual({ 'Jira project': 'OPS' })
    const none = planView({ ...NEW_AGENT, project: null } as PlanOut, form.rows)
    expect(none.kind === 'agents' && none.agents[0]?.found).toEqual({})
  })

  it('fills the Jira project the platform added to a draft from their words, so it is not asked', () => {
    const { name, rows } = answered24Hour.answer
    const drafted = planView(NEW_AGENT, cardFrom(name, rows as SetupCardReply['rows'], '').rows)
    expect(drafted.kind === 'agents' && drafted.agents[0]?.found).toEqual({ 'Jira project': 'MOCK' })
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

  it('never says a schedule the Planner filled in from their words is as they asked', () => {
    const note = 'I filled some of this in from your words “Every other Friday at 9am”. Please check it.'
    const rows = [{ kind: 'schedule' as const, text: 'Every Friday at 9am', state: 'changed' as const, note }, ...ROWS.rows.slice(1)]
    expect(checkedRows({ ...enterWhen(cardFrom('x', rows, '')), step: 4 })[0]).toEqual({ ok: false, words: `When: Every Friday at 9:00. ${note}` })
  })

  it('sends the name, the rows as the instruction, each agent’s values and the schedule, as a draft that is not on yet', () => {
    const form = { ...ready(), name: '  Follow up stale bugs ' }
    expect(createBody(form, planView(CLEAN_DRAFT, form.rows), { 0: 'crd_new' })).toEqual({
      name: 'Follow up stale bugs',
      instruction: 'Find bug tickets in MOCK with no update for 14 days. Create one follow-up ticket that lists them. Where it goes: Jira project MOCK.',
      agents: [{ card_id: 'crd_new', values: { 'Jira project': 'MOCK' } }],
      schedule: { day: 'weekdays', at: '15:00' },
      left_out: [],
      on: false,
    })
    const named = createBody({ ...form, name: '' }, planView(CLEAN_DRAFT, form.rows), { 0: 'crd_new' })
    expect(named.name).toBe('Stale bug follow-up')
  })
})

describe('pressing Set up', () => {
  const form = (): Form => ({ ...enterWhen(read(ROWS)), step: 4, name: 'Follow up stale bugs' })

  function fakeCalls(failing: number, saved: string | null = null): { readonly calls: SetUpCalls; readonly seen: string[] } {
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
    await expect(setUp(form(), plan, 'd1', cards, calls)).rejects.toBeInstanceOf(ApiError)
    expect(seen).toEqual(['look for Stale bug follow-up', 'save Stale bug follow-up', 'create with crd_new'])
    await expect(setUp(form(), plan, 'd1', cards, calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: false })
    expect(seen).toEqual(['look for Stale bug follow-up', 'save Stale bug follow-up', 'create with crd_new', 'create with crd_new', 'delete draft d1'])
  })

  it('uses the agent the Operator already saved for the same plan, and saves no copy', async () => {
    const { calls, seen } = fakeCalls(0, 'crd_saved')
    await expect(setUp(form(), planView(CLEAN_DRAFT, form().rows), null, new Map(), calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: false })
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
      blocks: (drafted.blocks ?? []).map((block) => ({ say: block.say, tool: (block.tool ?? null) as CardToolId | null })),
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
      blocks: (drafted.blocks ?? []).map((block) => ({ say: block.say, tool: (block.tool ?? null) as CardToolId | null })),
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
    await expect(setUp(form(), planView(USE_ONE, form().rows), null, new Map(), calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: false })
    expect(seen).toEqual(['create with crd_version_checker'])
  })

  it('still turns it on when the draft cannot be deleted, and says the draft is kept', async () => {
    const { calls, seen } = fakeCalls(4)
    await expect(setUp(form(), planView(CLEAN_DRAFT, form().rows), 'd1', new Map(), calls)).resolves.toEqual({ useCaseId: 'uc_new', draftKept: true })
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
    const content = JSON.parse(JSON.stringify(draftContent({ ...read(ROWS), carriedOn: true }, null))) as Record<string, unknown>
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


describe('the Planner’s set-up card', () => {
  const REPLY = setupCardAnswer as SetupCardReply
  const PART = partAnswer as PartReply
  const saved = (step: number, content: Record<string, unknown>): DraftView => ({ draft_id: 'd1', step, content, created_at: '2026-11-03T07:00:00Z', saved_at: '2026-11-03T07:00:00Z' })
  const fresh = () => cardFrom(REPLY.name, REPLY.rows, 'Every Friday, sum up the tickets we closed this week')
  const AGENTS = (inputs: readonly { name: string; kind: 'jira_project' }[]) =>
    planView(
      {
        decision: 'use_one',
        agents: [
          {
            card: { card_id: 'c1', name: 'Closed-ticket summary', inputs: inputs.map((input) => ({ ...input, what: 'Where to look' })), blocks: [] },
            values: {},
          },
        ],
      } as unknown as PlanOut,
      [],
    )

  it('starts from the Planner’s rows with a schedule read only from its words, so no time is guessed', () => {
    const form = fresh()
    expect(form.name).toBe('Weekly summary of closed tickets')
    expect(form.rows.map((row) => row.kind)).toEqual(['schedule', 'look_for', 'do', 'where'])
    expect(form.when).toMatchObject({ often: 'week', day: 'friday', at: '' })
    expect(whenSaid(form.when)).toBeNull()
  })

  it('never carries a part the platform can’t do, so the card of a partly-possible request holds only what runs', () => {
    const form = cardFrom(PART.name, PART.rows, 'sum up and email')
    expect(JSON.stringify(form.rows)).not.toMatch(/email/i)
    const withCant = cardFrom('x', [...PART.rows, { kind: 'do', text: 'Email the list', state: 'cant_do', note: 'No email.' }], '')
    expect(withCant.rows.some((row) => row.text.includes('Email'))).toBe(false)
  })

  describe('setupLeft', () => {
    it('lets the When section answer for the schedule: a schedule row with nothing in it is not asked for twice', () => {
      const form = cardFrom('x', [{ kind: 'schedule', text: '', state: 'missing', note: null }, { kind: 'do', text: 'List them', state: 'understood', note: null }], '')
      expect(setupLeft(form, null).choices).toEqual(['when it runs', 'the Planner to choose the agents'])
      const timed = { ...form, when: { often: 'every_day' as const, day: '' as const, at: '09:00', filledFrom: '' } }
      expect(setupLeft(timed, null).choices).toEqual(['the Planner to choose the agents'])
    })

    it('lists no time as what is left, and nothing else, once the parts are clear and the plan is in', () => {
      const plan = AGENTS([])
      expect(setupLeft(fresh(), plan).choices).toEqual(['when it runs'])
      const timed = { ...fresh(), when: { often: 'week' as const, day: 'friday' as const, at: '16:00', filledFrom: 'Every Friday' } }
      expect(setupLeft(timed, plan).choices).toEqual([])
    })

    it('adds the plan’s empty inputs, such as the Jira project, to the same list', () => {
      const plan = AGENTS([{ name: 'Jira project', kind: 'jira_project' }])
      expect(setupLeft(fresh(), plan).choices).toEqual(['when it runs', 'the Jira project'])
      const form = { ...fresh(), typed: { '0:Jira project': 'mock' } }
      expect(setupLeft(form, plan).choices).toEqual(['when it runs'])
    })

    it('says the Planner is still choosing the agents until the plan arrives, and counts a part it can’t do or is still checking', () => {
      const timed = { ...fresh(), when: { often: 'week' as const, day: 'friday' as const, at: '16:00', filledFrom: 'x' } }
      expect(setupLeft(timed, null).choices).toEqual(['the Planner to choose the agents'])
      const edited = changeRow(timed, 2, 'Email the list to the team')
      expect(setupLeft(edited, null).choices).toEqual(['my check of your new words'])
      expect(setupLeft(afterPartCheck(edited, edited.rows[2] as Row, checkCant as never), null).choices).toEqual(['a part I can’t do yet'])
    })

    it('is the one source of the footer line, with a count that follows the list', () => {
      expect(leftWords({ choices: [], leftOut: [] }), 'nothing left to answer says nothing: the button says what it sets up').toBe('')
      expect(leftWords({ choices: ['when it runs'], leftOut: [] })).toBe('1 question to answer')
      expect(leftWords({ choices: ['when it runs', 'the Jira project'], leftOut: [] })).toBe('2 questions to answer')
      expect(leftWords({ choices: ['the Planner to choose the agents'], leftOut: [] }), 'waiting on the Planner is no question for them').toBe('Waiting for the Planner…')
      expect(leftWords({ choices: ['my check of your new words'], leftOut: [] })).toBe('Checking your new words…')
      expect(andList(['a', 'b', 'c'])).toBe('a, b and c')
    })
  })

  it('checks a changed part again: a part that fits becomes yours, and one that does not, or gets no answer, stays one I can’t do', () => {
    const edited = changeRow(fresh(), 2, 'Sum them up in two tickets')
    const part = edited.rows[2] as Row
    expect(afterPartCheck(edited, part, { state: 'fits' }).rows[2]).toMatchObject({ state: 'edited', note: null })
    expect(afterPartCheck(edited, part, checkCant as never).rows[2]).toMatchObject({ state: 'cant_do' })
    expect(afterPartCheck(edited, part, null).rows[2]).toMatchObject({ state: 'cant_do', note: NOT_CHECKED })
  })

  describe('nextQuestion', () => {
    const CLASH = clashAnswer as SetupCardReply
    const words = (form: Form, plan: PlanView | null = null) => nextQuestion(form, plan)?.words ?? null
    const pick = (form: Form, label: string): Form => {
      const asked = nextQuestion(form, null)
      const choice = asked?.kind === 'when' ? asked.choices.find((one) => one.label === label) : undefined
      if (!choice) throw new Error(`No choice ${label} in ${JSON.stringify(asked)}`)
      return answerWhen(form, choice.set)
    }
    const said = (schedule: string, typed = schedule) => cardFrom('x', [{ kind: 'schedule', text: schedule, state: schedule ? 'understood' : 'missing', note: null }, ...REPLY.rows.slice(1)], typed)

    it('asks how often, then the day of a weekly run, then the time, one at a time, and nothing once the schedule is whole', () => {
      const start = said('')
      expect(words(start)).toBe('How often?')
      expect(nextQuestion(start, null)).toMatchObject({ kind: 'when', choices: [{ label: 'Every day' }, { label: 'Every weekday' }, { label: 'Every week' }, { label: 'Only when I run it' }] })
      const weekly = pick(start, 'Every week')
      expect(words(weekly)).toBe('Which day?')
      const friday = pick(weekly, 'Friday')
      expect(words(friday)).toBe('At what time?')
      expect(nextQuestion(friday, null)).toMatchObject({ choices: [{ label: '8:00' }, { label: '9:00' }, { label: '13:00' }, { label: '17:00' }] })
      const timed = pick(friday, '9:00')
      expect(whenSaid(timed.when)).toBe('Every Friday at 9:00')
      expect(nextQuestion(timed, null)).toBeNull()
    })

    it('never guesses a time: a named day with no time asks the time, and a bare hour asks morning or evening', () => {
      expect(words(said('Every Friday'))).toBe('At what time?')
      const bare = said('Every Friday at 9')
      expect(words(bare)).toBe('At 9:00 or 21:00?')
      expect(whenSaid(pick(bare, '21:00').when)).toBe('Every Friday at 21:00')
      expect(words(said('Every Friday at 12'))).toBe('At 0:00 or 12:00?')
      expect(whenSaid(said('Every Friday at 17').when)).toBe('Every Friday at 17:00')
    })

    it('asks which of two days the request named, never picking the first, and keeps the time it said', () => {
      const form = cardFrom(CLASH.name, CLASH.rows, 'Every Monday and Friday at 9am, sum up the closed tickets in MOCK', CLASH.parts)
      expect(form.when).toMatchObject({ often: 'week', day: '', at: '09:00' })
      expect(words(form)).toBe('Monday or Friday?')
      expect(nextQuestion(form, null)).toMatchObject({ choices: [{ label: 'Monday' }, { label: 'Friday' }] })
      expect(whenSaid(pick(form, 'Monday').when)).toBe('Every Monday at 9:00')
    })

    it('asks which of two times, and which of two frequencies, in the words of the choices', () => {
      const parts = (reason: 'one_time' | 'one_frequency', text: string, ...choices: string[]) => [{ text, mark: 'cant' as const, reason, note: null, choices }]
      const times = cardFrom('x', [{ kind: 'schedule', text: '', state: 'missing', note: null }], 'every Friday at 9am and 5pm list open tickets', parts('one_time', '9am and 5pm', '9am', '5pm'))
      expect(words(times)).toBe('9:00 or 17:00?')
      expect(whenSaid(pick(times, '17:00').when)).toBe('Every Friday at 17:00')
      const often = cardFrom('x', [{ kind: 'schedule', text: '', state: 'missing', note: null }], 'every day and every week at 9am, list tickets', parts('one_frequency', 'every day and every week', 'every day', 'every week'))
      expect(words(often)).toBe('Every day or Every week?')
    })

    it('then asks which tickets, the Jira project, and what it does, in that order', () => {
      const timed = (form: Form): Form => answerWhen(form, { often: 'every_day', at: '09:00' })
      const missing = (kind: RowKind) => ({ kind, text: '', state: 'missing' as const, note: null })
      const form = timed(cardFrom('x', [missing('look_for'), missing('do')], ''))
      expect(nextQuestion(form, null)).toEqual({ kind: 'row', index: 0, words: 'Which tickets should it find?' })
      const found = changeRow(form, 0, 'Closed tickets')
      const settled = { ...found, rows: found.rows.map((row) => ({ ...row, state: row.kind === 'look_for' ? ('edited' as const) : row.state })) }
      expect(nextQuestion(settled, AGENTS([{ name: 'Jira project', kind: 'jira_project' }]), ['MOCK'])).toEqual({ kind: 'input', agent: 0, input: 'Jira project', words: 'Create 1 Jira ticket in which project?', choices: ['MOCK'] })
      expect(nextQuestion({ ...settled, typed: { '0:Jira project': 'MOCK' } }, AGENTS([{ name: 'Jira project', kind: 'jira_project' }]))).toEqual({ kind: 'row', index: 1, words: 'What should it do with them?' })
    })
  })

  describe('the Jira project question', () => {
    const missing = (kind: RowKind, text = '') => ({ kind, text, state: (text === '' ? 'missing' : 'understood') as RowState, note: null })
    const ticket = (extra: Partial<Form> = {}): Form => ({
      ...answerWhen(cardFrom('x', [missing('schedule', 'Every weekday at 9am'), missing('look_for', 'New releases of langchain-ai/langgraph'), missing('do', 'Create a Jira ticket for each new one'), missing('where')], ''), { often: 'weekdays', at: '09:00' }),
      ...extra,
    })

    it('asks which Jira project the ticket goes in, with the projects the platform may use as choices, in place of where the result goes', () => {
      expect(nextQuestion(ticket(), TICKET_PLAN, ['MOCK'])).toEqual({ kind: 'project', index: 3, words: 'Create 1 Jira ticket in which project?', choices: ['MOCK'] })
    })

    it('still asks, with no choices, when the platform names no project, so a key can be typed', () => {
      expect(nextQuestion(ticket(), TICKET_PLAN)).toMatchObject({ kind: 'project', words: 'Create 1 Jira ticket in which project?', choices: [] })
    })

    it('asks where the result goes, as before, when nothing in the request is a Jira ticket', () => {
      const note = cardFrom('x', [missing('schedule', 'Every weekday at 9am'), missing('look_for', 'New releases of langchain-ai/langgraph'), missing('do', 'Show me the version'), missing('where')], '')
      expect(nextQuestion(answerWhen(note, { often: 'weekdays', at: '09:00' }), null, ['MOCK'])).toEqual({ kind: 'row', index: 3, words: 'Where should the result go?' })
    })

    it('one click answers it: the where part is filled in, the plan can be asked for, and the project fills the agent’s Jira input', () => {
      const asked = ticket()
      expect(cardBlockers(asked.rows).map((blocker) => blocker.words)).toEqual(['you say where it goes'])
      const chosen = chooseProject(asked, 'MOCK')
      expect(chosen.rows[3]).toMatchObject({ kind: 'where', text: 'In the MOCK project', state: 'edited' })
      expect(cardBlockers(chosen.rows)).toEqual([])
      expect(taskWithoutSchedule(chosen.rows)).toContain('Where it goes: In the MOCK project.')
      const plan = planView({ ...(NEW_AGENT as object), project: null } as PlanOut, chosen.rows)
      const agent = plan.kind === 'agents' ? plan.agents[0] : undefined
      expect(agent && valueOf(chosen, agent, 'Jira project')).toBe('MOCK')
      expect(nextQuestion(chosen, plan, ['MOCK'])).toBeNull()
    })

    it('keeps the Planner’s own words for the where part, so changing it back puts them back', () => {
      const chosen = chooseProject(ticket(), 'OPS')
      expect(chosen.rows[3]?.planner).toMatchObject({ text: '', state: 'missing' })
    })

    it('uses the same words when a drafted agent’s Jira project is still empty', () => {
      const where = ticket({ rows: ticket().rows.map((row) => (row.kind === 'where' ? { ...row, text: 'In Jira', state: 'understood' as const } : row)) })
      const asked = nextQuestion(where, AGENTS([{ name: 'Jira project', kind: 'jira_project' }]), ['MOCK', 'OPS'])
      expect(asked).toMatchObject({ kind: 'input', words: 'Create 1 Jira ticket in which project?', choices: ['MOCK', 'OPS'] })
    })
  })

  describe('every open question at once', () => {
    const missing = (kind: RowKind, text = '') => ({ kind, text, state: (text === '' ? 'missing' : 'understood') as RowState, note: null })
    const blank = () => cardFrom('x', [missing('schedule'), missing('look_for', 'New releases of langchain-ai/langgraph'), missing('do', 'Create a Jira ticket'), missing('where')], '')

    it('lists How often?, At what time? and the Jira project together, in the order of the card', () => {
      expect(questionsOf(blank(), TICKET_PLAN, ['MOCK']).map((q) => q.words)).toEqual(['How often?', 'At what time?', 'Create 1 Jira ticket in which project?'])
    })

    it('asks the day beside the time once every week is chosen, and no time for Only when I run it', () => {
      const weekly = answerWhen(blank(), { often: 'week' })
      expect(questionsOf(weekly, TICKET_PLAN, []).map((q) => q.words).slice(0, 2)).toEqual(['Which day?', 'At what time?'])
      const manual = answerWhen(blank(), { often: 'manual' })
      expect(questionsOf(manual, TICKET_PLAN, []).map((q) => q.words)).toEqual(['Create 1 Jira ticket in which project?'])
    })

    it('never guesses a time: a day without one still asks At what time?', () => {
      const day = answerWhen(blank(), { often: 'weekdays' })
      expect(questionsOf(day, TICKET_PLAN, []).map((q) => q.words)).toContain('At what time?')
    })

    it('is empty once nothing is left to ask, and the first of the list is the next question', () => {
      const done = chooseProject(answerWhen(blank(), { often: 'weekdays', at: '09:00' }), 'MOCK')
      expect(questionsOf(done, TICKET_PLAN, ['MOCK'])).toEqual([])
      expect(nextQuestion(blank(), TICKET_PLAN, ['MOCK'])).toEqual(questionsOf(blank(), TICKET_PLAN, ['MOCK'])[0])
    })

    it('counts the open parts, not the questions: When is one part', () => {
      expect(openParts(blank())).toBe(2)
      expect(answerFirst({ choices: ['when it runs', 'where it goes'], leftOut: [] })).toBe('Pick 2 more to finish')
      expect(answerFirst({ choices: ['where it goes'], leftOut: [] })).toBe('Pick 1 more to finish')
      expect(answerFirst({ choices: [], leftOut: [] })).toBeNull()
    })
  })

  describe('the repository row', () => {
    const missing = (kind: RowKind, text = '') => ({ kind, text, state: (text === '' ? 'missing' : 'understood') as RowState, note: null })
    const fastapi = () => answerWhen(cardFrom('x', [missing('schedule', 'Every weekday at 9am'), missing('look_for', 'New releases of FastAPI'), missing('do', 'Tell me here'), missing('where', 'Here in the chat')], ''), { often: 'weekdays', at: '09:00' })
    const MATCHES = [
      { repo: 'fastapi/fastapi', what: 'FastAPI web framework' },
      { repo: 'tiangolo/fastapi', what: 'An older address' },
    ]

    it('names the software the card watches, and no software when the row already holds owner/name', () => {
      expect(softwareOf(fastapi())).toBe('FastAPI')
      const known = cardFrom('x', [missing('look_for', 'New releases of langchain-ai/langgraph')], '')
      expect(softwareOf(known)).toBeNull()
      expect(repoMissing(known)).toBe(false)
      expect(softwareOf(cardFrom('x', [missing('look_for', 'Tickets closed this week in MOCK')], ''))).toBeNull()
    })

    it('is a question until a repository is chosen, and the footer counts it', () => {
      expect(repoMissing(fastapi())).toBe(true)
      expect(setupLeft(fastapi(), null).choices.filter(isQuestion)).toEqual(['the GitHub repository'])
      expect(answerFirst(setupLeft(fastapi(), null))).toBe('Pick 1 more to finish')
      const chosen = chooseRepo(fastapi(), 'fastapi/fastapi', true)
      expect(repoMissing(chosen)).toBe(false)
      expect(setupLeft(chosen, null).choices.filter(isQuestion)).toEqual([])
    })

    it('asks first, before When and the Jira project, with each match as a choice', () => {
      const asked = questionsOf(fastapi(), null, ['MOCK'], { state: 'found', matches: MATCHES })
      expect(asked[0]).toEqual({ kind: 'repo', words: 'Which repository should I watch?', choices: MATCHES, checking: false, note: null })
    })

    it('is looking while the finder works, and has no choices when it found none', () => {
      expect(questionsOf(fastapi(), null, [], { state: 'checking' })[0]).toMatchObject({ kind: 'repo', checking: true, choices: [] })
      expect(questionsOf(fastapi(), null, [], { state: 'none' })[0]).toMatchObject({ kind: 'repo', checking: false, choices: [] })
    })

    it('is filled by the one clear match, and again by Change after a choice', () => {
      const one = [{ repo: 'fastapi/fastapi', what: 'FastAPI web framework' }]
      expect(effectiveRepo(fastapi(), one)).toBe('fastapi/fastapi')
      expect(questionsOf(fastapi(), null, [], { state: 'found', matches: one })).toEqual([])
      const cleared = { ...fastapi(), typed: { [REPO_CHOICE]: '' } }
      expect(effectiveRepo(cleared, one)).toBeNull()
      expect(questionsOf(cleared, null, [], { state: 'found', matches: one })[0]).toMatchObject({ kind: 'repo', choices: one })
    })

  })

  describe('what Change and the finder do to the repository and the project', () => {
    const missing = (kind: RowKind, text = '') => ({ kind, text, state: (text === '' ? 'missing' : 'understood') as RowState, note: null })
    const watch = (text: string) => answerWhen(cardFrom('x', [missing('schedule', 'Every weekday at 9am'), missing('look_for', text), missing('do', 'Tell me here'), missing('where', 'Here in the chat')], ''), { often: 'weekdays', at: '09:00' })
    const AGENT = (kinds: readonly ('github_repo' | 'jira_project')[] = ['github_repo']) =>
      planView(
        {
          decision: 'use_one',
          agents: [{ card: { card_id: 'c1', name: 'Release check', inputs: kinds.map((kind) => ({ name: kind === 'github_repo' ? 'GitHub repository' : 'Jira project', kind, what: 'It reads this.' })), blocks: [] }, values: {}, part: '', missing: [] }],
          reason: '',
          questions: [],
        } as unknown as PlanOut,
        [],
      )
    const input = (plan: PlanView, name: string) => {
      const agent = plan.kind === 'agents' ? plan.agents[0] : undefined
      if (!agent) throw new Error('no agent')
      return { agent, name }
    }

    it('sends the agent the repository the finder filled, and nothing stale once the Watch part is changed to other software', () => {
      const plan = AGENT()
      const { agent, name } = input(plan, 'GitHub repository')
      const filled = chooseRepo(watch('New releases of FastAPI'), 'fastapi/fastapi', true)
      expect(valueOf(filled, agent, name)).toBe('fastapi/fastapi')
      const changed = changeRow(filled, 1, 'New releases of React')
      expect(changed.typed[REPO_CHOICE], 'the old choice is gone').toBeUndefined()
      expect(changed.typed[REPO_FOUND]).toBeUndefined()
      expect(softwareOf(changed)).toBe('React')
      expect(repoMissing(changed), 'the finder is asked again for the new software').toBe(true)
      expect(valueOf(changed, agent, name), 'no stale repository goes to the agent').toBe('')
    })

    it('sends the agent the owner/name the person types in the Watch part', () => {
      const plan = AGENT()
      const { agent, name } = input(plan, 'GitHub repository')
      const filled = chooseRepo(watch('New releases of FastAPI'), 'fastapi/fastapi', true)
      const typed = changeRow(filled, 1, 'django/django')
      expect(softwareOf(typed), 'owner/name is a repository, not a name to look up').toBeNull()
      expect(repoMissing(typed)).toBe(false)
      expect(effectiveRepo(typed)).toBe('django/django')
      expect(valueOf(typed, agent, name)).toBe('django/django')
    })

    it('keeps the repository cleared by Change cleared: the agent gets none until one is picked', () => {
      const plan = AGENT()
      const { agent, name } = input(plan, 'GitHub repository')
      const cleared = chooseRepo(chooseRepo(watch('New releases of FastAPI'), 'fastapi/fastapi', true), '')
      expect(valueOf(cleared, agent, name)).toBe('')
      expect(repoMissing(cleared)).toBe(true)
    })

    it('sends only the software name to the finder, not the words around it', () => {
      expect(softwareOf(watch('New releases of LangGraph on GitHub'))).toBe('LangGraph')
      expect(softwareOf(watch('New releases of FastAPI from GitHub'))).toBe('FastAPI')
      const typed = changeRow(watch('New releases of FastAPI'), 1, 'React')
      expect(softwareOf(typed), 'a bare name the person typed in the Watch part').toBe('React')
      expect(softwareOf(watch('Tickets closed this week in MOCK'))).toBeNull()
    })

    it('asks no text box of the agent’s Jira project or GitHub repository: the row’s choice is the one source', () => {
      const plan = AGENT(['github_repo', 'jira_project'])
      const form = chooseProject(chooseRepo(watch('New releases of FastAPI'), 'fastapi/fastapi', true), 'MOCK')
      expect(plan.kind === 'agents' && plan.agents[0]?.inputs.map((one) => valueOf(form, plan.agents[0] as PlanAgent, one.name))).toEqual(['fastapi/fastapi', 'MOCK'])
      expect(questionsOf(form, plan, ['MOCK'], { state: 'found', matches: [] })).toEqual([])
      expect(JIRA_CHOICE).toBe('jira_project')
    })

    it('counts one number: the lead and the footer read the same function, with the plan and the finder’s fill in it', () => {
      const plan = AGENT(['github_repo'])
      const open = watch('New releases of FastAPI')
      expect(openParts(open, plan)).toBe(1)
      expect(answerFirst(setupLeft(open, plan))).toBe('Pick 1 more to finish')
      const filled = chooseRepo(open, 'fastapi/fastapi', true)
      expect(openParts(filled, plan)).toBe(0)
      expect(answerFirst(setupLeft(filled, plan))).toBeNull()
    })

    it('never guesses a ticket write: a Jira word in a read is not a write, and only a plan with the write asks the project', () => {
      const reads = cardFrom('x', [missing('schedule', 'Every Friday at 5pm'), missing('look_for', 'The Jira tickets we closed this week'), missing('do', 'Sum up the Jira tickets we closed'), missing('where')], '')
      const form = answerWhen(reads, { often: 'week', day: 'friday', at: '17:00' })
      const readPlan = planView({ decision: 'use_one', agents: [{ card: { card_id: 'c', name: 'Summary', inputs: [], blocks: [{ say: 'Find them.', tool: 'jira.search' }] }, values: {}, part: '', missing: [] }], reason: '', questions: [] } as unknown as PlanOut, [])
      expect(hasTicketWrite(readPlan)).toBe(false)
      expect(nextQuestion(form, readPlan, ['MOCK'])).toEqual({ kind: 'row', index: 3, words: 'Where should the result go?' })
      const writePlan = planView({ ...(NEW_AGENT as object), project: null } as PlanOut, [])
      expect(hasTicketWrite(writePlan)).toBe(true)
      expect(nextQuestion(form, writePlan, ['MOCK'])).toMatchObject({ kind: 'project', index: 3, choices: ['MOCK'] })
    })

    it('waits for the plan before asking where the result goes, so no empty chip flashes', () => {
      const form = answerWhen(cardFrom('x', [missing('schedule', 'Every Friday at 5pm'), missing('look_for', 'Closed tickets'), missing('do', 'Create a Jira ticket'), missing('where')], ''), { often: 'week', day: 'friday', at: '17:00' })
      expect(questionsOf(form, null, ['MOCK'], null, true)).toEqual([])
    })

    it('shows each finder trouble in its own words, never the words for no match', () => {
      const form = watch('New releases of FastAPI')
      const asked = (repos: RepoFind) => questionsOf(form, null, [], repos)[0]
      expect(asked({ state: 'none' })).toMatchObject({ kind: 'repo', note: null, checking: false })
      expect(asked({ state: 'trouble', words: 'GitHub did not answer.' })).toMatchObject({ kind: 'repo', note: 'GitHub did not answer.', checking: false })
      expect(asked({ state: 'checking' })).toMatchObject({ kind: 'repo', checking: true, note: null })
    })

    it('does not send a picked project back through the Planner’s check when a draft reopens', () => {
      const chosen = chooseProject(
        answerWhen(cardFrom('x', [missing('schedule', 'Every Friday at 5pm'), missing('look_for', 'Closed tickets'), missing('do', 'Create a Jira ticket'), missing('where')], ''), { often: 'week', day: 'friday', at: '17:00' }),
        'MOCK',
      )
      const saved = draftContent(chosen, null)
      const reopened = restoreDraft({ draft_id: 'd1', step: 2, content: saved, created_at: '2026-11-03T07:00:00Z', saved_at: '2026-11-03T07:00:00Z' })
      expect(reopened.form.rows.find((row) => row.kind === 'where')).toMatchObject({ text: 'In the MOCK project', state: 'edited' })
      expect(reopened.form.rows.some((row) => row.state === 'checking')).toBe(false)
    })
  })

  describe('what the Watch words may name as a repository, and one count for the lead and the footer', () => {
    const missing = (kind: RowKind, text = '') => ({ kind, text, state: (text === '' ? 'missing' : 'understood') as RowState, note: null })
    const rows = (look: string, when = 'Every weekday at 9am') => cardFrom('x', [missing('schedule', when), missing('look_for', look), missing('do', 'Tell me here'), missing('where', 'Here in the chat')], '')
    const ONE = [{ repo: 'fastapi/fastapi', what: 'FastAPI web framework' }]

    it('reads owner/name only as the release target, a GitHub address or the whole phrase, never any a/b in the words', () => {
      expect(effectiveRepo(rows('Tickets opened/closed this week'))).toBeNull()
      expect(softwareOf(rows('Tickets opened/closed this week'))).toBeNull()
      expect(effectiveRepo(rows('New releases of tiangolo/fastapi on GitHub'))).toBe('tiangolo/fastapi')
      expect(effectiveRepo(rows('github.com/django/django'))).toBe('django/django')
      expect(effectiveRepo(rows('django/django'))).toBe('django/django')
    })

    it('counts the same for the lead and the footer: one function of the form, the plan and the finder’s answer', () => {
      const noTime = rows('New releases of FastAPI', 'Every weekday')
      expect(openPartsFor(noTime, null, [])).toBe(2)
      expect(openPartsFor(noTime, null, ONE), 'one clear match fills the repository').toBe(1)
      expect(openParts(noTime), 'the form alone is the same function with nothing from the finder').toBe(openPartsFor(noTime, null, []))
    })
  })

  describe('setupLeft with crosses', () => {
    const CROSS = crossAnswer as SetupCardReply
    const CLASH = clashAnswer as SetupCardReply
    const plan = AGENTS([])

    it('keeps them words for each cross, which never stop Turn it on but change its name and the footer', () => {
      const form = cardFrom(CROSS.name, CROSS.rows, 'Every Friday at 5pm, sum up the tickets we closed this week in MOCK and colour them by team', CROSS.parts)
      const left = setupLeft(form, plan)
      expect(left).toEqual({ choices: [], leftOut: ['colour them by team'] })
      expect(leftWords(left), 'the cross is on the card, so the foot needn’t say it again').toBe('')
      expect(setUpWords(), 'a cross is on the card, so the button keeps its name').toBe('Turn on')
    })

    it('never says nothing is unclear while a part has a cross, and a choice still left comes first', () => {
      const form = cardFrom(CROSS.name, CROSS.rows.slice(1), 'sum up the tickets and colour them by team', CROSS.parts)
      expect(leftWords(setupLeft(form, plan))).toBe('1 question to answer')
    })

    it('names only the day left out once they pick one of two, and sends that as left_out', () => {
      const form = cardFrom(CLASH.name, CLASH.rows, 'Every Monday and Friday at 9am, sum up the closed tickets in MOCK', CLASH.parts)
      expect(setupLeft(form, plan)).toEqual({ choices: ['when it runs'], leftOut: ['Monday and Friday'] })
      const monday = answerWhen(form, { often: 'week', day: 'monday' })
      expect(setupLeft(monday, plan)).toEqual({ choices: [], leftOut: ['Friday'] })
      expect(createBody(monday, plan, {}).left_out).toEqual(['Friday'])
      const tuesday = answerWhen(form, { often: 'week', day: 'tuesday' })
      expect(setupLeft(tuesday, plan).leftOut).toEqual(['Monday and Friday'])
    })

    it('asks how many days when the words name none, until they change which tickets it finds', () => {
      const asked = { ...fresh(), when: { often: 'week' as const, day: 'friday' as const, at: '16:00', filledFrom: 'x' }, marked: [{ text: 'stale', mark: 'question' as const, reason: 'how_many_days' as const, note: null, choices: [] }] }
      expect(setupLeft(asked, plan).choices).toEqual(['how many days'])
      expect(nextQuestion(asked, plan)?.kind).toBe('days')
      const changed = changeRow(asked, 1, 'Bug tickets not updated for 10 days')
      expect(changed.marked).toEqual([])
    })

    it('keeps the crosses in a saved draft, so Workflows says the same', () => {
      const form = cardFrom(CROSS.name, CROSS.rows, 'x', CROSS.parts)
      const draft = saved(2, JSON.parse(JSON.stringify(draftContent(form, null))) as Record<string, unknown>)
      expect(restoreDraft(draft).form.marked).toEqual(form.marked)
      expect(savedLeft(draft)?.leftOut).toEqual(['colour them by team'])
      const old = saved(2, JSON.parse(JSON.stringify({ ...draftContent(form, null), form: { ...form, marked: undefined } })) as Record<string, unknown>)
      expect(restoreDraft(old).form.marked).toEqual([])
    })

    it.each([
      ['track them', 'which_software'],
      ['monthly', 'how_often'],
      ['rename it', 'only_schedule'],
      ['pause the morning check', 'operators'],
    ] as const)('keeps “%s” in a saved draft, with its reason %s', (text, reason) => {
      const crossed: PartView = { text, mark: 'cant', reason, note: null, choices: [] }
      const form = cardFrom(CROSS.name, CROSS.rows, 'x', [...CROSS.parts, crossed])
      const draft = saved(2, JSON.parse(JSON.stringify(draftContent(form, null))) as Record<string, unknown>)
      expect(restoreDraft(draft).form.marked).toContainEqual(crossed)
    })
  })

  it('gives a saved card’s draft the same list setupLeft gives the open card, and none for a draft with only words', () => {
    const card = { ...fresh(), name: 'Mine' }
    const draft = saved(2, JSON.parse(JSON.stringify(draftContent(card, null))) as Record<string, unknown>)
    expect(savedLeft(draft)).toEqual(setupLeft(card, null))
    expect(savedLeft(saved(2, { intent: 'Every Wednesday, find tickets' }))).toBeNull()
  })
})

describe('pressing on the set-up card', () => {
  const built = { type: 'built', useCaseId: 'uc_1', draftKept: false, newAgents: [] } as const

  it('Set up makes it Building, the platform’s answer builds it, and a refusal opens the card again', () => {
    expect(cardPhase({ kind: 'open' }, { type: 'set_up', key: 'press_1' }), 'a press keeps its key, so a card drawn again finds its answer').toEqual({ kind: 'creating', key: 'press_1' })
    expect(cardPhase({ kind: 'creating', key: 'press_1' }, built)).toEqual({ kind: 'built', useCaseId: 'uc_1', draftKept: false, newAgents: [] })
    expect(cardPhase({ kind: 'creating', key: 'press_1' }, { type: 'refused' })).toEqual({ kind: 'open' })
    expect(cardPhase({ kind: 'creating', key: 'press_1' }, { type: 'refused', said: ['Name it.'] }), 'the card keeps the platform’s words').toEqual({ kind: 'open', refused: ['Name it.'] })
    expect(cardPhase({ kind: 'built', useCaseId: 'uc_1', draftKept: false, newAgents: [] }, { type: 'set_up', key: 'press_2' }), 'a second press sets up nothing more').toEqual({ kind: 'built', useCaseId: 'uc_1', draftKept: false, newAgents: [] })
  })

  it('Never mind drops an open card, never one being set up, and Undo opens a dropped one again', () => {
    expect(cardPhase({ kind: 'open' }, { type: 'never_mind' })).toEqual({ kind: 'dropped' })
    expect(cardPhase({ kind: 'creating', key: 'press_1' }, { type: 'never_mind' })).toEqual({ kind: 'creating', key: 'press_1' })
    expect(cardPhase({ kind: 'dropped' }, { type: 'undo' })).toEqual({ kind: 'open' })
    expect(cardPhase({ kind: 'dropped' }, { type: 'set_up', key: 'press_3' })).toEqual({ kind: 'dropped' })
  })
})

describe('what the footer counts', () => {
  it('counts only the questions the card asks, and says what else waits in its own words', () => {
    expect(leftWords({ choices: ['when it runs', 'a part I can’t do yet'], leftOut: [] }), 'a part they must change is no question').toBe('1 question to answer')
    expect(leftWords({ choices: ['a part I can’t do yet'], leftOut: [] })).toBe('Change the part I can’t do yet, or leave it out.')
    expect(leftWords({ choices: ['a request I can do'], leftOut: [] })).toBe('Change your words to something I can do.')
    expect(isQuestion('the Jira project')).toBe(true)
    expect(isQuestion('nothing left out for want of a tool')).toBe(false)
  })
})

describe('a second workflow of the same name', () => {
  it('gets the next number, so Set up another never makes two of one name', () => {
    expect(secondName('LangGraph release check')).toBe('LangGraph release check 2')
    expect(secondName('LangGraph release check 2')).toBe('LangGraph release check 3')
  })

  it('asks the time in the words of how often it runs', () => {
    expect(timeWords({ often: 'every_day', day: '', at: '', filledFrom: null })).toBe('Every day, at what time?')
    expect(timeWords({ often: 'weekdays', day: '', at: '', filledFrom: null })).toBe('Every weekday, at what time?')
    expect(timeWords({ often: 'week', day: 'monday', at: '', filledFrom: null })).toBe('Mondays, at what time?')
  })
})

describe('the card’s draft saves and deletes', () => {
  /** A request the server has not answered yet, and the order the server handled each one. */
  const server = () => {
    const handled: string[] = []
    const pending = (name: string) => {
      let answer: (ok: boolean) => void = () => undefined
      const request = new Promise<void>((resolve, reject) => {
        answer = (ok) => {
          handled.push(name)
          if (ok) resolve()
          else reject(new Error(`${name} failed`))
        }
      })
      return { request, answer }
    }
    return { handled, pending }
  }
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

  it('deletes only after a save still on its way has landed, so the save can’t bring the draft back (#190)', async () => {
    const { handled, pending } = server()
    const writes = draftWrites()
    const save = pending('save')
    void writes.saved(save.request)
    const deleted = writes.afterSaves(() => {
      handled.push('delete')
      return Promise.resolve()
    })
    await tick()
    expect(handled, 'the delete waits while the save is on its way').toEqual([])
    save.answer(true)
    await deleted
    expect(handled).toEqual(['save', 'delete'])
  })

  it('still deletes after a save that failed, and at once when nothing is being saved', async () => {
    const { handled, pending } = server()
    const writes = draftWrites()
    const save = pending('save')
    writes.saved(save.request).catch(() => undefined)
    const deleted = writes.afterSaves(() => {
      handled.push('delete')
      return Promise.resolve()
    })
    save.answer(false)
    await deleted
    expect(handled).toEqual(['save', 'delete'])
    await writes.afterSaves(() => {
      handled.push('delete again')
      return Promise.resolve()
    })
    expect(handled.at(-1)).toBe('delete again')
  })
})

describe('a 24-hour time from the Planner', () => {
  const CAROL = 'Every Friday at 16:00, find Jira tickets in project MOCK that nobody updated for 14 days, and raise one Jira ticket in MOCK that lists them'
  const timed = (schedule: string) => cardFrom('x', [{ kind: 'schedule', text: schedule, state: 'understood', note: null }], schedule)

  it('reads their time from the schedule row the runtime sends, and never asks for it again', () => {
    const { name, rows } = answered24Hour.answer
    const form = cardFrom(name, rows as SetupCardReply['rows'], CAROL)
    expect(form.when).toMatchObject({ often: 'week', day: 'friday', at: '16:00' })
    expect(whenSaid(form.when)).toBe('Every Friday at 16:00')
    expect(nextQuestion(form, null)?.kind).not.toBe('when')
  })

  it.each([
    ['Every Friday at 00:00', '00:00'],
    ['Every Friday at 23:55', '23:55'],
    ['Every Friday at 4pm', '16:00'],
  ])('reads “%s” as %s', (schedule, at) => {
    expect(timed(schedule).when.at).toBe(at)
    expect(nextQuestion(timed(schedule), null)).toBeNull()
  })

  it.each(['Every Friday at 24:00', 'Every Friday at 7:5', 'Every Friday at 1600', 'Every Friday at 23:59'])('asks the time for “%s”, never a guess', (schedule) => {
    expect(nextQuestion(timed(schedule), null)).toMatchObject({ kind: 'when', field: 'at' })
  })
})

describe('a workflow that runs only when someone presses Run now', () => {
  const said = (schedule: string): Form =>
    cardFrom('x', [{ kind: 'schedule', text: schedule, state: schedule ? 'understood' : 'missing', note: null }, ...ROWS.rows.slice(1)], schedule ? `${schedule}, ${FOLLOW_UP}` : FOLLOW_UP)
  const choose = (form: Form, label: string): Form => {
    const asked = nextQuestion(form, null)
    const choice = asked?.kind === 'when' ? asked.choices.find((one) => one.label === label) : undefined
    if (!choice) throw new Error(`No choice ${label} in ${JSON.stringify(asked)}`)
    return answerWhen(form, choice.set)
  }
  const saved = (content: Record<string, unknown>): DraftView => ({ draft_id: 'd1', step: 2, content, created_at: '2026-11-23T07:00:00Z', saved_at: '2026-11-23T07:00:00Z' })

  it('offers Only when I run it as the fourth answer to How often?, and asks no time after it', () => {
    const start = said('')
    expect(nextQuestion(start, null)).toMatchObject({
      kind: 'when',
      field: 'often',
      words: 'How often?',
      choices: [{ label: 'Every day' }, { label: 'Every weekday' }, { label: 'Every week' }, { label: 'Only when I run it' }],
    })
    const manual = choose(start, 'Only when I run it')
    expect(nextQuestion(manual, null)).toBeNull()
    expect(whenProblems(manual.when)).toEqual({})
    expect(whenSaid(manual.when)).toBe('Only when I run it')
    expect(setupLeft(manual, null).choices).not.toContain('when it runs')
  })

  it.each(['Only when I ask', 'When I run it', 'Only when I run it', 'On demand', 'Run it manually', 'Only run manually', 'Only manually'])('reads “%s” as no schedule, with no time to ask', (words) => {
    expect(readWhen(words)).toMatchObject({ often: 'manual', day: '', at: '' })
    expect(nextQuestion(said(words), null)).toBeNull()
  })

  it.each([
    'Whenever',
    'As needed',
    'Now and then',
    'When it suits me',
    'Manually',
    'Check n8n releases so I don’t have to check manually',
    "I don't want to run it manually",
    'Nobody should run it manually',
    'Tickets we triaged manually',
    'On demand or weekly',
    'On demand, or once a month',
  ])('asks How often? for “%s”, never a guess', (words) => {
    expect(readWhen(words).often).toBe('')
    expect(nextQuestion(said(words), null)?.words).toBe('How often?')
  })

  it('keeps a schedule written beside the words, since Run now starts any workflow', () => {
    expect(readWhen('On demand, and also weekly on Monday at 9am')).toMatchObject({ often: 'week', day: 'monday', at: '09:00' })
  })

  it('sends no schedule, even after a time was picked first', () => {
    const timed = choose(choose(said(''), 'Every day'), '9:00')
    const manual = answerWhen(timed, { often: 'manual' })
    expect(whenSaid(manual.when)).toBe('Only when I run it')
    expect(scheduleOf(manual.when)).toBeNull()
    const body = createBody({ ...manual, step: 4 }, planView(CLEAN_DRAFT, manual.rows), { 0: 'crd_new' })
    expect(body.schedule).toBeNull()
  })

  it('says it was as they asked, and a saved draft reopens with it', () => {
    const form = said('On demand')
    expect(checkedRows(form)[0]).toEqual({ ok: true, words: 'When: Only when I run it, as you asked.' })
    const content = JSON.parse(JSON.stringify(draftContent(form, null))) as Record<string, unknown>
    expect(restoreDraft(saved(content)).form.when).toMatchObject({ often: 'manual' })
  })
})
