import { useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useStartDrafting } from '../../api/draftedQueries'
import type { DraftedWorkflowView } from '../../api/types'
import { newIdempotencyKey } from '../../api/idempotency'
import { pressOnce, useLatch } from '../../api/latch'
import { useAsker } from '../home/asker'
import { useShowDraft } from '../home/ChatProvider'
import { ANY_BLOCK } from './drafted'
import styles from './Drafted.module.css'

/**
 * The quiet link on a card (ADR 0053, item 5): the Planner already picked how to build it, and this sends the same words to the
 * drafter, which may use any n8n block. For an Operator, and only when the platform sent words to draft. Nothing is drafted until it
 * is pressed, and the words go unchanged.
 */
export function AnyBlockLink({ words }: { words: string | null }) {
  const operator = useAsker() === 'operator'
  const show = useShowDraft()
  const start = useStartDrafting()
  const latch = useLatch()
  const errorWords = useErrorWords()
  const [key] = useState(newIdempotencyKey)
  const [problem, setProblem] = useState<string | null>(null)
  if (!operator || words === null || show === null) return null
  return (
    <div>
      <button
        type="button"
        className={styles['linkButton']}
        aria-busy={start.isPending || undefined}
        onClick={() => {
          if (start.isPending) return
          pressOnce<DraftedWorkflowView>(latch, (outcome) => start.mutate({ words, idempotencyKey: key }, outcome), {
            onSuccess: (view) => {
              setProblem(null)
              show(view.drafted_id)
            },
            onError: (error) => setProblem(errorWords(error)),
          })
        }}
      >
        {ANY_BLOCK}
      </button>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  )
}
