import { useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import { useAnswerFix, useFix, useStartFix, useTurnBackOn } from '../../api/fixQueries'
import { pressOnce, useLatch } from '../../api/latch'
import type { FixQuestionView, FixView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { FixCrew } from './FixCrew'
import { askFix, fixLine, fixStageOf, HANDED_BACK_HEAD, handedBackWords, NEXT_STEP, type Ask, type FixStage } from './fixCard'
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

/** The one setting a hand-back asks a person for, which a fix never changes itself: a button for each choice, and a box to type in. */
function Question({ fixId, question }: { fixId: string; question: FixQuestionView }) {
  const answer = useAnswerFix(fixId)
  const latch = useLatch()
  const words = useErrorWords()
  const [typing, setTyping] = useState(false)
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
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
      {question.choices.length > 0 || question.typed !== null ? (
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
      {typing ? (
        <form className={styles['typeForm']} onSubmit={submit}>
          <input ref={(node) => node?.focus()} type="text" autoComplete="off" className={styles['input']} aria-label={question.typed ?? 'Type it here'} placeholder="Type it here" value={text} onChange={(event) => setText(event.target.value)} />
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

function HandedBack({ fix, view, now }: { fix: FixState; view: FixView | undefined; now: number }) {
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
          {view.question ? <Question fixId={view.fix_id} question={view.question} /> : null}
          <p>{NEXT_STEP}</p>
          <div className={styles['buttons']}>
            <ButtonLink to={`/workflows/${encodeURIComponent(view.use_case_id)}`}>Open the workflow</ButtonLink>
          </div>
        </>
      ) : null}
    </>
  )
}

function Next({ stage, fix, view, operator, now }: { stage: FixStage | 'ready'; fix: FixState; view: FixView | undefined; operator: boolean; now: number }) {
  switch (stage) {
    case 'ready':
      return view?.approval_id ? (
        <div className={styles['buttons']}>
          <ButtonLink to={`/setup-approvals/${encodeURIComponent(view.approval_id)}`}>Open the approval</ButtonLink>
        </div>
      ) : null
    case 'approved':
      if (view === undefined || !view.can_turn_back_on) return null
      return operator ? <TurnBackOn fixId={view.fix_id} /> : <p className={styles['hint']}>{OPERATOR_TURNS_ON}</p>
    case 'handed_back':
      return <HandedBack fix={fix} view={view} now={now} />
    default:
      return null
  }
}

/**
 * The run's fix under the stop, drawn from one source for each fact: the activity says which sub-agents came in and each round,
 * and the platform's own state says where the fix stands, in its own words. Past its deadline a fix reads as ended, never as
 * spinning. An Operator asks for one on a stop a retry won't fix, and everyone else reads why not.
 */
export function FixSection({
  runId,
  fix,
  operator,
  next,
  modelOff,
  now,
  loadedUpTo,
}: {
  runId: string
  fix: FixState | null
  operator: boolean
  next: 'retry' | 'report' | undefined
  modelOff: boolean
  now: number
  loadedUpTo?: number
}) {
  const query = useFix(fix?.id ?? null)
  const view = query.data
  const stage = fixStageOf(fix, view, now)
  const ask = askFix({ operator, next, stage, modelOff })
  if (fix === null || stage === null) return ask === null ? null : (
    <div className={styles['fix']}>
      <Ask runId={runId} ask={ask} />
    </div>
  )
  const ended = stage === 'handed_back'
  return (
    <div className={styles['fix']}>
      <FixCrew fix={fix} now={now} line={ended ? null : fixLine(fix, view, now)} {...(loadedUpTo === undefined ? {} : { loadedUpTo })} />
      {ended ? <p className={styles['head']}>{HANDED_BACK_HEAD}</p> : null}
      <Next stage={stage} fix={fix} view={view} operator={operator} now={now} />
      {ask === null ? null : <Ask runId={runId} ask={ask} />}
    </div>
  )
}
