import { useContext, useEffect, useId, useState, type ReactNode } from 'react'
import { useErrorWords } from '../../api/context'
import { useMe, useUseCase, useWatchlist } from '../../api/queries'
import type { EditChoice, EditReply } from '../../api/types'
import { useChatScheduleChange, useChatWatchlistSchedule, useUndoVersion, useVersions } from '../../api/workflowQueries'
import { Button, ButtonLink } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { OpenButton } from '../../ui/OpenItem'
import { nextRunAt, undoProblem } from '../workflows/workflow'
import type { Page } from './AnswerCards'
import { CardMemoryContext } from './cardMemory'
import {
  changedSince,
  crossesOf,
  doneLine,
  doneSay,
  editView,
  firstPicks,
  openSay,
  pressSave,
  publishedVersion,
  scheduleText,
  sinceUnversioned,
  targetOf,
  type Now,
  type Phase,
  type Picks,
  type Question,
  type Read,
  type Schedule,
} from './edit'
import { crossParts, PartsList, type Part } from './PartsList'
import { useMainButton } from './primary'
import { useSaidOnce, type Say } from './StateAnswers'
import styles from './EditCard.module.css'
import partsStyles from './PartsList.module.css'
import setup from './SetupCard.module.css'

type Focus = 'heading' | 'save' | 'undo'

interface EditCardProps {
  readonly reply: EditReply
  /** What she typed, which says whether she meant "it". */
  readonly typed: string
  readonly page: Page
  readonly say: Say
  readonly now: Date
  /** The workflow the answer before this one was about, which "it" means. */
  readonly about: string | null
}

const software = (count: number | undefined): string => (count === undefined ? 'the software' : count === 1 ? 'the one software' : `all ${String(count)} software`)

/** The watchlist's schedule is everyone's: saving it makes her its owner, so she can't approve its checks (spec 6.7). */
function watchlistNote(saved: boolean, count: number | undefined): string {
  return saved
    ? `This changed when ${software(count)} on the watchlist are checked, and made you the owner of this schedule. Its checks count as your work now, so you can’t approve them.`
    : `This changes when ${software(count)} on the watchlist are checked. Saving makes you the owner of this schedule. Its checks then count as your work, so you won’t be able to approve them.`
}

/**
 * The edit card (spec 6.7): a change to when a workflow runs, before and after, that saves only when she presses Save change.
 * Saving publishes a new version through the schedule route the workflow's page uses, with Undo. The Software watchlist's
 * schedule keeps no versions, so its card offers no Undo. The sentence and the card are worked out on every draw from the
 * workflow as the platform holds it now, so a later change anywhere shows here.
 */
export function EditCard({ reply, typed, page, say, now, about }: EditCardProps) {
  const memory = useContext(CardMemoryContext).edit
  const [kept] = useState(memory.kept)
  const [picks, setPicks] = useState<Picks>(kept?.picks ?? firstPicks(reply, about, typed))
  const [phase, setPhase] = useState<Phase>(kept?.phase ?? { kind: 'open' })
  const [problem, setProblem] = useState<string | null>(null)
  const [another, setAnother] = useState<string | null>(null)
  const id = useId()
  const main = useMainButton()
  const words = useErrorWords()
  const me = useMe()
  const saveChange = useChatScheduleChange()
  const saveWatchlist = useChatWatchlistSchedule()
  const undoVersion = useUndoVersion()
  const saving = saveChange.isPending || saveWatchlist.isPending

  useEffect(() => memory.keep({ picks, phase }))

  const picked = targetOf(reply, picks)
  const target: EditChoice | null = phase.kind === 'saved' || phase.kind === 'undone' ? phase.target : picked
  const live = useUseCase(target?.use_case_id ?? '', target !== null)
  // Only a read made since the card was drawn says whether its Before is still true. An older read in the cache can't.
  const read: Read =
    !live.isFetchedAfterMount || (!live.data && !live.isError)
      ? { kind: 'reading' }
      : live.isError || !live.data
        ? { kind: 'failed' }
        : { kind: 'read', schedule: live.data.schedule ? { day: live.data.schedule.day, at: live.data.schedule.at } : null, version: live.data.version }
  const view = editView(reply, picks, read)
  const versions = useVersions(target?.use_case_id ?? '', live.data?.version ?? 0)
  const watchlist = useWatchlist({ enabled: target?.watchlist === true || (view.kind === 'missing' && view.software !== null) })

  const mine = phase.kind === 'saved' ? phase.version : phase.kind === 'undone' ? phase.version : null
  const since = mine !== null ? changedSince(live.data, versions.data, mine) : phase.kind === 'saved' ? sinceUnversioned(phase.after, read) : null
  const nextAt = target?.watchlist ? watchlist.data?.schedule?.next_at : live.data?.next_run_at
  const zone = target?.watchlist ? watchlist.data?.schedule?.time_zone : live.data?.schedule?.time_zone
  const state: Now = { paused: live.data?.state === 'paused', next: nextAt ? nextRunAt(nextAt, now, zone) : null }
  const sentence = phase.kind === 'open' ? openSay(reply, view, watchlist.data?.schedule?.day ?? null) : doneSay(phase, state, since, live.data)
  useSaidOnce(sentence, say)

  // After a press the card draws again, so focus moves once the new state is on the page.
  const focusSoon = (what: Focus) => setTimeout(() => document.getElementById(`${id}-${what}`)?.focus(), 0)

  const pick = (next: Partial<Picks>, then: Focus) => {
    setPicks((before) => ({ ...before, ...next }))
    setAnother(null)
    focusSoon(then)
  }

  // Kept in the chat's memory at once, so a save that lands after she left Home still shows, with its Undo, when she comes back.
  const settle = (next: Phase, then: Focus) => {
    memory.keep({ picks, phase: next })
    setProblem(null)
    setPhase(next)
    focusSoon(then)
  }

  const saved = (after: Schedule, version: number | null, chosen: EditChoice) => settle({ kind: 'saved', target: chosen, after, version }, version === null ? 'heading' : 'undo')

  const save = () => {
    const press = pressSave(view, read)
    if (press.kind === 'ask') document.getElementById(`${id}-question`)?.querySelector('button')?.focus()
    if (press.kind !== 'send') return
    const { target: chosen, after, known } = press
    const failed = (error: unknown) => setProblem(`Could not save the change. ${words(error)}`)
    if (chosen.watchlist) {
      saveWatchlist.mutate({ useCaseId: chosen.use_case_id, schedule: after }, { onSuccess: () => saved(after, null, chosen), onError: failed })
      return
    }
    saveChange.mutate(
      { useCaseId: chosen.use_case_id, schedule: after },
      { onSuccess: ({ view: answer, newest }) => saved(after, publishedVersion(chosen, answer, newest, me.data?.id, known), chosen), onError: failed },
    )
  }

  const undo = () => {
    if (phase.kind !== 'saved' || phase.version === null) return
    const { target: chosen, after, version } = phase
    undoVersion.mutate(
      { useCaseId: chosen.use_case_id, version },
      {
        onSuccess: (answer) => settle({ kind: 'undone', target: chosen, after, version: answer.version }, 'heading'),
        onError: (error) => setProblem(undoProblem(version, chosen.name, error, words)),
      },
    )
  }

  const neverMind = () => {
    if (saving) return
    memory.keep({ picks, phase: { kind: 'kept' } })
    setPhase({ kind: 'kept' })
    page.box()
  }

  const said = (
    <p id={`${id}-sentence`} className={styles['sentence']}>
      {sentence}
    </p>
  )
  if (phase.kind === 'kept') return said

  const crosses = phase.kind === 'open' ? crossParts(crossesOf(reply, view), { workflow: target?.name ?? '' }) : []
  const asked = (key: string, label: string, { words: asks, choices }: Pick<Question, 'words' | 'choices'>, choose: (value: string) => void, more?: ReactNode): Part => ({
    key,
    mark: 'ask',
    label,
    body: (
      <>
        <span className={setup['pq']} id={`${id}-q-${key}`}>
          {asks}
        </span>
        <span className={setup['pick']} role="group" aria-labelledby={`${id}-q-${key}`} id={`${id}-question`}>
          {choices.map((choice) => (
            <button key={choice.value} type="button" className={setup['choice']} onClick={() => choose(choice.value)}>
              {choice.label}
            </button>
          ))}
          {more}
        </span>
      </>
    ),
  })

  if (phase.kind === 'open' && view.kind === 'which') {
    if (view.choices.length === 0) return said
    const question = { words: 'Which workflow?', choices: view.choices.map((choice) => ({ label: choice.name, value: choice.use_case_id })) }
    return (
      <>
        {said}
        <Card id={id} title="Change a workflow">
          <PartsList parts={[asked('which', 'Workflow', question, (useCaseId) => pick({ useCaseId }, 'heading')), ...crosses]} />
        </Card>
      </>
    )
  }

  if (phase.kind === 'open' && (view.kind === 'missing' || view.kind === 'cant' || view.kind === 'same' || view.kind === 'stale' || view.kind === 'unread')) {
    const next =
      view.kind === 'missing' && view.software !== null ? (
        <Button variant={main} onClick={() => page.ask(`Keep track of the ${view.software ?? ''} version`)}>
          Watch {view.software}
        </Button>
      ) : view.kind === 'cant' && view.target !== null ? (
        <OpenButton variant={main} item={{ kind: 'workflow', id: view.target.use_case_id }} to={`/workflows/${encodeURIComponent(view.target.use_case_id)}`}>
          Open {view.target.name}
        </OpenButton>
      ) : null
    return (
      <>
        {said}
        {crosses.length > 0 ? (
          <div className={partsStyles['leftovers']}>
            <PartsList parts={crosses} />
          </div>
        ) : null}
        {next ? <div className={styles['next']}>{next}</div> : null}
      </>
    )
  }

  const shown = phase.kind === 'open' ? (view.kind === 'held' || view.kind === 'ask' || view.kind === 'ready' ? view : null) : null
  const chosen = target
  if (chosen === null || (phase.kind === 'open' && shown === null)) return said

  const question = shown?.kind === 'ask' ? shown.question : null
  const askPart: Part[] =
    question === null
      ? []
      : [
          asked('when', 'When', question, (value) => pick(question.field === 'day' ? { day: value as Picks['day'] } : { at: value }, 'save'), question.another ? (
            <button type="button" className={setup['choice']} aria-expanded={another !== null} onClick={() => setAnother((open) => (open === null ? '' : null))}>
              Another time
            </button>
          ) : null),
        ]
  const onStep = another !== null && /^\d{2}:\d[05]$/.test(another)
  const anotherTime =
    question?.another && another !== null ? (
      <form
        className={styles['another']}
        onSubmit={(event) => {
          event.preventDefault()
          if (onStep) pick({ at: another }, 'save')
        }}
      >
        <label htmlFor={`${id}-another`}>Time, Singapore</label>
        <input id={`${id}-another`} type="time" step={300} value={another} aria-describedby={`${id}-another-help`} onChange={(event) => setAnother(event.target.value)} />
        <Button type="submit">Use this time</Button>
        <span id={`${id}-another-help`} className={styles['note']}>
          {another !== '' && !onStep ? 'Pick a time on a 5-minute step, such as 8:05.' : ''}
        </span>
      </form>
    ) : null
  const pickedTime = phase.kind === 'open' && shown?.kind === 'ready' && (picks.day !== null || picks.at !== null)

  const after: ReactNode =
    phase.kind !== 'open' ? (
      <b>{scheduleText(phase.after)}</b>
    ) : shown?.kind === 'ready' ? (
      <>
        <b>{scheduleText(shown.after)}</b>
        {pickedTime ? (
          <button type="button" className={setup['link']} onClick={() => pick({ day: null, at: null }, 'heading')}>
            Change<span className="visually-hidden"> when it runs</span>
          </button>
        ) : null}
      </>
    ) : shown?.kind === 'ask' ? (
      <span className="muted">{shown.question.field === 'day' ? 'Choose a day' : 'Choose a time'}</span>
    ) : (
      <span className="muted">Unchanged</span>
    )

  const done = phase.kind === 'saved' || phase.kind === 'undone' ? doneLine(phase, state, since) : null
  const held = shown?.kind === 'held'
  return (
    <>
      {said}
      <Card
        id={id}
        title={`Change ${chosen.name}`}
        action={
          phase.kind === 'open' && reply.use_case_id === null ? (
            <button type="button" className={setup['link']} onClick={() => pick({ useCaseId: null, day: null, at: null }, 'heading')}>
              Pick another workflow
            </button>
          ) : null
        }
      >
        <PartsList parts={[...askPart, ...crosses]} />
        {anotherTime}
        <div className={setup['part']}>
          <h4>When it runs</h4>
          <dl className={styles['ba']}>
            <dt>Before</dt>
            <dd>{chosen.before ? scheduleText(chosen.before) : 'Not scheduled'}</dd>
            <dt>After</dt>
            <dd>{after}</dd>
          </dl>
          {chosen.watchlist ? <p className={styles['note']}>{watchlistNote(phase.kind !== 'open', watchlist.data?.software.length)}</p> : null}
        </div>
        <div className={setup['foot']}>
          {done || held ? null : (
            <Button id={`${id}-save`} variant={main} loading={saving || read.kind === 'reading'} aria-describedby={question ? `${id}-q-when` : undefined} onClick={save}>
              Save change
            </Button>
          )}
          <p role="status" className={done ? styles['status'] : setup['left']}>
            {done ? (
              <>
                <IconCheck size={14} /> {done.words}
              </>
            ) : held ? (
              crosses.length > 0 ? 'Ask again without the part with a cross.' : 'Ask again with the day or the time.'
            ) : null}
          </p>
          {done?.undo ? (
            <Button id={`${id}-undo`} loading={undoVersion.isPending} onClick={undo}>
              Undo<span className="visually-hidden"> the change to {chosen.name}</span>
            </Button>
          ) : null}
          {done && chosen.watchlist ? <ButtonLink to="/software">Change it on the Software page</ButtonLink> : null}
          {done ? null : <Button onClick={neverMind}>Never mind</Button>}
        </div>
        {problem ? (
          <p className={styles['problem']} role="alert">
            {problem}
          </p>
        ) : null}
      </Card>
    </>
  )
}

function Card({ id, title, action, children }: { id: string; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className={setup['card']} aria-labelledby={`${id}-heading`} data-card="edit">
      <div className={setup['head']}>
        <h3 id={`${id}-heading`} tabIndex={-1}>
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  )
}

