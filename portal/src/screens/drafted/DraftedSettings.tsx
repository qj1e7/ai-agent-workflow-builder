import { useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import { useAnswerDrafted } from '../../api/draftedQueries'
import { pressOnce, useLatch } from '../../api/latch'
import type { DraftedWorkflowView, DraftSettingView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconPencil } from '../../ui/icons'
import { Words } from '../explain/Report'
import { guessesOf, questionOf, typedPlaceholder, waitingOf } from './drafted'
import styles from './Drafted.module.css'

interface Picks {
  readonly view: DraftedWorkflowView
  readonly setting: DraftSettingView
  /** Called after the platform took an answer. */
  readonly onAnswered?: () => void
}

/** One button for each choice, and a button that opens a box to type in when the platform reads typed answers. A refusal shows under them. */
function AnswerPicks({ view, setting, onAnswered }: Picks) {
  const words = useErrorWords()
  const answer = useAnswerDrafted(view.drafted_id)
  const latch = useLatch()
  const [typing, setTyping] = useState(false)
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const send = (body: { choice: string } | { typed: string }) =>
    pressOnce(latch, (outcome) => answer.mutate({ revision: view.revision, setting: setting.id, ...body }, outcome), {
      onSuccess: () => {
        setProblem(null)
        setTyping(false)
        setText('')
        onAnswered?.()
      },
      onError: (error) => setProblem(words(error)),
    })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    // An empty box answers nothing, so nothing is sent.
    if (text.trim() === '') return
    send({ typed: text.trim() })
  }
  return (
    <>
      <span className={styles['picks']}>
        {setting.choices.map((choice) => (
          <Button key={choice.value} loading={answer.isPending} onClick={() => send({ choice: choice.value })}>
            {choice.label}
          </Button>
        ))}
        {setting.typed !== null ? (
          <Button aria-expanded={typing} onClick={() => setTyping((was) => !was)}>
            {setting.typed}
          </Button>
        ) : null}
      </span>
      {typing ? (
        <form className={styles['typeForm']} onSubmit={submit}>
          <input
            // The box opened on a press for it, so focus goes to it.
            ref={(node) => node?.focus()}
            type="text"
            autoComplete="off"
            className={styles['input']}
            aria-label={setting.typed ?? 'Type it here'}
            placeholder={typedPlaceholder(setting.kind)}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <Button type="submit" loading={answer.isPending}>
            Set
          </Button>
        </form>
      ) : null}
      {problem ? (
        <span className={styles['problem']} role="alert">
          {problem}
        </span>
      ) : null}
    </>
  )
}

/** The one question the platform asks now: its key, its words, and its answers. */
function QuestionRow({ view, setting }: { view: DraftedWorkflowView; setting: DraftSettingView }) {
  return (
    <li className={styles['part']}>
      <span className={styles['icon']} role="img" aria-label="Question">
        ?
      </span>
      <span className={styles['key']}>{setting.key}</span>
      <span className={styles['value']}>
        <span>{setting.question}</span>
        <AnswerPicks view={view} setting={setting} />
      </span>
    </li>
  )
}

/** A setting the drafter guessed, shown as a guess with a way to change it. */
function GuessRow({ view, setting }: { view: DraftedWorkflowView; setting: DraftSettingView }) {
  const [changing, setChanging] = useState(false)
  return (
    <li className={styles['part']}>
      <span className={styles['icon']} role="img" aria-label="Guess">
        <IconPencil aria-hidden="true" />
      </span>
      <span className={styles['key']}>{setting.key}</span>
      <span className={styles['value']}>
        <span>
          <span className={styles['chip']}>{setting.value}</span> <span className={styles['note']}>I guessed.</span>{' '}
          <button type="button" className={styles['linkButton']} aria-expanded={changing} aria-label={`Change ${setting.key}`} onClick={() => setChanging((was) => !was)}>
            Change
          </button>
        </span>
        {changing ? <AnswerPicks view={view} setting={setting} onAnswered={() => setChanging(false)} /> : null}
      </span>
    </li>
  )
}

/** A setting that cannot be answered now, with the platform's reason and nothing to press. */
function WaitingRow({ setting }: { setting: DraftSettingView }) {
  return (
    <li className={styles['part']}>
      <span className={styles['icon']} role="img" aria-label="Waiting">
        ?
      </span>
      <span className={styles['key']}>{setting.key}</span>
      <span className={styles['value']}>
        <span>
          <Words segments={setting.label} />
        </span>
        <span className={styles['note']}>{setting.waits}</span>
      </span>
    </li>
  )
}

/** What a draft asks and shows about its settings: the question, then what waits, then guesses. Nothing but a draft asks. */
export function DraftedSettings({ view }: { view: DraftedWorkflowView }) {
  if (view.state !== 'draft' || view.in_n8n !== null) return null
  const question = questionOf(view)
  const guesses = guessesOf(view)
  const waits = waitingOf(view)
  if (question === null && guesses.length === 0 && waits.length === 0) return null
  return (
    <ul className={styles['parts']} aria-label="Settings">
      {question ? <QuestionRow key={question.id} view={view} setting={question} /> : null}
      {waits.map((setting) => (
        <WaitingRow key={setting.id} setting={setting} />
      ))}
      {guesses.map((setting) => (
        <GuessRow key={setting.id} view={view} setting={setting} />
      ))}
    </ul>
  )
}
