import { useContext, useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useDisplayName } from '../../api/people'
import { useMe, useUseCase } from '../../api/queries'
import type { ChangedInN8nReply } from '../../api/types'
import { useAddTheYesBack, useRollback, useUseCaseInN8n } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Pill } from '../../ui/Pill'
import { IconCheck } from '../../ui/icons'
import { useTakeBackPress } from '../workflows/InN8n'
import { ADD_THE_YES_BACK, backToVersionToast, gradePill, UNDO, yesBackToast } from '../workflows/n8nChange'
import { heldOf, heldWords, mayTakeBack, openingOf, TAKE_IT_BACK } from '../workflows/n8nHold'
import { useAsker } from './asker'
import { CardMemoryContext } from './cardMemory'
import { buttonsOf, OPEN, problemOf, refusedPhase, statusOf, wordsOf, type Phase } from './changed'
import { useNote } from './ChatProvider'
import { useMainButton } from './primary'
import editStyles from './EditCard.module.css'
import styles from './Planner.module.css'

const TONE = { ok: 'ok', err: 'bad' } as const

/**
 * The sketch's Changed in n8n card: a version someone published in n8n's editor, graded by the safety checker. Add the yes back
 * and Undo each publish a new version, naming the version the person saw in use, so a change made since is never thrown away.
 * While someone has the workflow open in n8n both would be refused, so the card names who, read from the workflow itself so every
 * Operator sees it, with Take it back for those who may.
 */
export function ChangedInN8nAnswer({ reply }: { reply: ChangedInN8nReply }) {
  const operator = useAsker() === 'operator'
  const main = useMainButton()
  const memory = useContext(CardMemoryContext)
  const note = useNote()
  const errorWords = useErrorWords()
  const rollback = useRollback()
  const addYes = useAddTheYesBack()
  const [phase, setPhase] = useState<Phase>(() => memory.changed.kept() ?? OPEN)
  const me = useMe().data
  const nameOf = useDisplayName()
  const n8nAccess = operator && me?.n8n_access === true
  const useCase = useUseCase(reply.use_case_id, operator).data
  const inN8n = useUseCaseInN8n(reply.use_case_id, { enabled: n8nAccess })
  const held = operator && me && useCase ? heldOf(useCase, me, openingOf(inN8n)) : null
  const takeBack = useTakeBackPress(reply.use_case_id, held, note)
  const settle = (next: Phase) => {
    memory.changed.keep(next)
    setPhase(next)
  }
  const busy = rollback.isPending || addYes.isPending
  const words = wordsOf(reply, nameOf)
  const offered = buttonsOf(reply, phase, operator)
  const buttons = held ? { yes: false, undo: false } : offered
  const takesBack = held !== null && mayTakeBack(held) && (offered.yes || offered.undo)
  const status = statusOf(reply, phase)
  const problem = takeBack.problem ?? problemOf(phase)
  const pill = gradePill(reply.grade)
  const answers = (toast: (saved: number) => string) => ({
    onSuccess: (view: { readonly version: number }) => {
      settle({ kind: 'settled', version: view.version })
      note(toast(view.version))
    },
    onError: (error: unknown) => settle(refusedPhase(errorWords(error))),
  })
  const send = { useCaseId: reply.use_case_id, inUse: reply.version, via: 'chat' } as const

  return (
    <Card
      title="Changed in n8n"
      pill={
        <Pill tone={TONE[pill.tone]} data-changed-pill>
          {pill.label}
        </Pill>
      }
      status={
        status ? (
          <span role="status" className={status.good ? editStyles['saved'] : undefined}>
            {status.good ? <IconCheck size={14} /> : null}
            {status.words}
          </span>
        ) : undefined
      }
      actions={
        takesBack ? (
          <Button loading={takeBack.pending} onClick={takeBack.press}>
            {TAKE_IT_BACK}
          </Button>
        ) : buttons.yes || buttons.undo ? (
          <>
            {buttons.yes ? (
              <Button variant={main} loading={addYes.isPending} onClick={() => !busy && addYes.mutate(send, answers(yesBackToast))}>
                {ADD_THE_YES_BACK}
              </Button>
            ) : null}
            {buttons.undo ? (
              <Button loading={rollback.isPending} onClick={() => !busy && rollback.mutate({ ...send, version: reply.version - 1 }, answers((saved) => backToVersionToast(reply.version - 1, saved)))}>
                {UNDO}
                <span className="visually-hidden"> the change to {reply.name}</span>
              </Button>
            ) : null}
          </>
        ) : undefined
      }
    >
      <p>{words.who}</p>
      {words.unknown ? <p className={styles['note']}>{words.unknown}</p> : null}
      {words.changes.length > 0 ? (
        <ul className={styles['lines']}>
          {words.changes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {words.refused ? <p className={styles['note']}>{words.refused}</p> : null}
      {held ? <p className={styles['note']}>{heldWords(held, new Date())}</p> : null}
      {words.findings.length > 0 ? (
        <ul className={styles['lines']}>
          {words.findings.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </Card>
  )
}
