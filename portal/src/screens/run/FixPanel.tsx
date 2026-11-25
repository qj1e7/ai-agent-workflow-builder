import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import { useAnswerFix, useFix, useStartedFix, useStartFix, useTurnBackOn } from '../../api/fixQueries'
import { pressOnce, useLatch } from '../../api/latch'
import type { FixOffer, FixQuestionView, FixView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { FixCrew } from './FixCrew'
import { askFix, fixLeads, fixLine, fixStageOf, HANDED_BACK_HEAD, handedBackWords, NEXT_STEP, OPERATOR_ANSWERS, type Ask, type FixStage } from './fixCard'
import type { FixState } from './runModel'
import styles from './FixPanel.module.css'

const ASK_HINT = 'Drafts a change to the failed block, and proves it on practice systems. Nothing changes until an Approver says yes.'
const OPERATOR_TURNS_ON = 'An Operator turns it back on.'
const NO_ROUND = 'No round finished.'

/** Fix it for me, on a stopped run. The platform says at once if it can't start, and its words show here. */
function AskButton({ runId }: { runId: string }) {
  const start = useStartFix(runId)
  const latch = useLatch()
  const words = useErrorWords()
  const [problem, setProblem] = useState<string | null>(null)
  return (
    <>
      <p className={styles['hint']}>{ASK_HINT}</p>
      <div className={styles['buttons']}>
        <Button
          variant="primary"
          loading={start.isPending}
          onClick={() => pressOnce(latch, (outcome) => start.mutate(undefined, outcome), { onSuccess: () => setProblem(null), onError: (error) => setProblem(words(error)) })}
        >
          Fix it for me
        </Button>
      </div>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </>
  )
}

function Ask({ runId, ask }: { runId: string; ask: Ask }) {
  return ask.is === 'button' ? <AskButton runId={runId} /> : <p className={styles['hint']}>{ask.words}</p>
}

/** Only after an Approver's yes. The platform runs the one real test run, and the card then shows how it went. */
function TurnBackOn({ fixId }: { fixId: string }) {
  const turn = useTurnBackOn(fixId)
  const latch = useLatch()
  const words = useErrorWords()
  const [problem, setProblem] = useState<string | null>(null)
  return (
    <>
      <div className={styles['buttons']}>
        <Button
          variant="primary"
          loading={turn.isPending}
          onClick={() => pressOnce(latch, (outcome) => turn.mutate(undefined, outcome), { onSuccess: () => setProblem(null), onError: (error) => setProblem(words(error)) })}
        >
          Turn back on
        </Button>
      </div>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </>
  )
}

/**
 * The one setting a hand-back asks a person for, which a fix never changes itself: a button for each choice, and a box to type
 * in. Only an Operator can answer, so anyone else reads the question and a note, with no live button.
 */
function Question({ fixId, question, operator }: { fixId: string; question: FixQuestionView; operator: boolean }) {
  const answer = useAnswerFix(fixId)
  const latch = useLatch()
  const words = useErrorWords()
  const [typing, setTyping] = useState(false)
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const box = useRef<HTMLInputElement>(null)
  // Focus goes to the box only when the person opens it, never on a later redraw.
  useEffect(() => {
    if (typing) box.current?.focus()
  }, [typing])
  const send = (body: { choice: string } | { typed: string }) =>
    pressOnce(latch, (outcome) => answer.mutate({ setting: question.setting, ...body }, outcome), {
      onSuccess: () => {
        setProblem(null)
        setTyping(false)
        setText('')
      },
      onError: (error) => setProblem(words(error)),
    })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (text.trim() === '') return
    send({ typed: text.trim() })
  }
  return (
    <div className={styles['ask']}>
      <p>
        <b>{question.key}</b> {question.words}
      </p>
      {question.waits ? <p className={styles['hint']}>{question.waits}</p> : null}
      {!operator ? (
        <p className={styles['hint']}>{OPERATOR_ANSWERS}</p>
      ) : question.choices.length > 0 || question.typed !== null ? (
        <div className={styles['picks']}>
          {question.choices.map((choice) => (
            <Button key={choice.value} loading={answer.isPending} onClick={() => send({ choice: choice.value })}>
              {choice.label}
            </Button>
          ))}
          {question.typed !== null ? (
            <Button aria-expanded={typing} onClick={() => setTyping((was) => !was)}>
              {question.typed}
            </Button>
          ) : null}
        </div>
      ) : null}
      {operator && typing ? (
        <form className={styles['typeForm']} onSubmit={submit}>
          <input ref={box} type="text" autoComplete="off" className={styles['input']} aria-label={question.typed ?? 'Type it here'} placeholder="Type it here" value={text} onChange={(event) => setText(event.target.value)} />
          <Button type="submit" loading={answer.isPending}>
            Set
          </Button>
        </form>
      ) : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  )
}

function HandedBack({ fix, view, now, operator }: { fix: FixState; view: FixView | undefined; now: number; operator: boolean }) {
  const why = handedBackWords(fix, now)
  return (
    <>
      <dl className={styles['said']}>
        {why ? (
          <div>
            <dt>Why I stopped</dt>
            <dd>{why}</dd>
          </div>
        ) : null}
        <div>
          <dt>What I tried</dt>
          <dd>
            {fix.rounds.length > 0 ? (
              <ul className={styles['rounds']}>
                {fix.rounds.map((round) => (
                  <li key={round}>{round}</li>
                ))}
              </ul>
            ) : (
              NO_ROUND
            )}
          </dd>
        </div>
      </dl>
      {view ? (
        <>
          {view.question ? <Question fixId={view.fix_id} question={view.question} operator={operator} /> : null}
          <p>{NEXT_STEP}</p>
          <div className={styles['buttons']}>
            <ButtonLink to={`/workflows/${encodeURIComponent(view.use_case_id)}`}>Open the workflow</ButtonLink>
          </div>
        </>
      ) : null}
    </>
  )
}

function Next({ stage, fix, view, operator, approverId, now }: { stage: FixStage; fix: FixState; view: FixView | undefined; operator: boolean; approverId: string | null; now: number }) {
  switch (stage) {
    case 'ready': {
      if (!view?.approval_id) return null
      const to = `/setup-approvals/${encodeURIComponent(view.approval_id)}`
      return (
        <div className={styles['buttons']}>
          {approverId !== null && view.asked_by !== approverId ? (
            <ButtonLink variant="primary" to={to}>
              Review the fix
            </ButtonLink>
          ) : (
            <ButtonLink to={to}>Open the approval</ButtonLink>
          )}
        </div>
      )
    }
    case 'approved':
      if (view === undefined || !view.can_turn_back_on) return null
      return operator ? <TurnBackOn fixId={view.fix_id} /> : <p className={styles['hint']}>{OPERATOR_TURNS_ON}</p>
    case 'handed_back':
      return <HandedBack fix={fix} view={view} now={now} operator={operator} />
    default:
      return null
  }
}

interface FixingProps {
  readonly runId: string
  readonly fix: FixState | null
  readonly operator: boolean
  readonly next: 'retry' | 'report' | undefined
  /** The platform's answer to whether a fix can start on this stop. Nothing until it has said. */
  readonly offer: FixOffer | null | undefined
  readonly now: number
  /** The signed-in person's id when they are an Approver, else null. */
  readonly approverId?: string | null
}

function useFixing({ runId, fix, operator, next, offer, now, approverId = null }: FixingProps) {
  const view = useFix(fix?.id ?? null).data
  const started = useStartedFix(runId)
  const stage = fixStageOf(fix, view, now)
  // A press the platform answered, before the run's own events carry the fix: nothing more to ask.
  const waiting = fix === null && started !== undefined && started.state !== 'handed_back'
  const ask = waiting ? null : askFix({ operator, next, offer, stage })
  const leads = waiting ? false : fixLeads({ ask, stage, view, operator, approverId })
  return { view, started: waiting ? started : undefined, stage, ask, leads }
}

/** Whether the fix holds the stop's one main button, so the stop's own next step steps back to a plain one. */
export function useFixLeads(props: FixingProps): boolean {
  return useFixing(props).leads
}

/**
 * The run's fix under the stop, drawn from one source for each fact: the activity says which sub-agents came in and each round,
 * and the platform's own state says where the fix stands, in its own words. Past its deadline a fix reads as ended, never as
 * spinning. An Operator asks for one when the platform says it can start, and everyone else reads why not.
 */
export function FixSection(props: FixingProps & { loadedUpTo?: number }) {
  const { runId, fix, operator, now, loadedUpTo, approverId = null } = props
  const { view, started, stage, ask } = useFixing(props)
  if (started) {
    return (
      <div className={styles['fix']}>
        <p role="status">{started.said}</p>
      </div>
    )
  }
  if (fix === null || stage === null) {
    return ask === null ? null : (
      <div className={styles['fix']}>
        <Ask runId={runId} ask={ask} />
      </div>
    )
  }
  const ended = stage === 'handed_back'
  return (
    <div className={styles['fix']}>
      <FixCrew fix={fix} now={now} line={ended ? null : fixLine(fix, view, now)} {...(loadedUpTo === undefined ? {} : { loadedUpTo })} />
      {ended ? <p className={styles['head']}>{HANDED_BACK_HEAD}</p> : null}
      <Next stage={stage} fix={fix} view={view} operator={operator} approverId={approverId} now={now} />
      {ask === null ? null : <Ask runId={runId} ask={ask} />}
    </div>
  )
}
