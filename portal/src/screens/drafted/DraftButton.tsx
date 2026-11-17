import { useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useStartDrafting } from '../../api/draftedQueries'
import type { DraftedWorkflowView } from '../../api/types'
import { newIdempotencyKey } from '../../api/idempotency'
import { pressOnce, useLatch } from '../../api/latch'
import { Button } from '../../ui/Button'
import { useAsker } from '../home/asker'
import { useShowDraft } from '../home/ChatProvider'
import { DRAFT_BUTTON } from './drafted'
import styles from './Drafted.module.css'

/**
 * Under an answer that can't set a workflow up as asked: the button that sends the same words to the drafter, for an Operator and
 * only when the platform sent words to draft. Nothing is drafted until it is pressed, and the words go unchanged.
 */
export function DraftButton({ words }: { words: string | null }) {
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
      <Button
        loading={start.isPending}
        onClick={() =>
          pressOnce<DraftedWorkflowView>(latch, (outcome) => start.mutate({ words, idempotencyKey: key }, outcome), {
            onSuccess: (view) => {
              setProblem(null)
              show(view.drafted_id)
            },
            onError: (error) => setProblem(errorWords(error)),
          })
        }
      >
        {DRAFT_BUTTON}
      </Button>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  )
}
