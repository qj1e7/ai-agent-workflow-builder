import { useContext, useState } from 'react'
import { ApiError } from '../../api/client'
import { useUseCase } from '../../api/queries'
import type { ExplainReply } from '../../api/types'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Link } from '../../ui/Link'
import { OpenButton } from '../../ui/OpenItem'
import type { Page } from '../home/AnswerCards'
import { CardMemoryContext } from '../home/cardMemory'
import chat from '../home/Planner.module.css'
import { sentenceOf } from '../workflows/workflow'
import { explainAnswerOf, explainAsk } from './explain'

export const MOST_WHICH = 8

function Which({ reply, page }: { reply: ExplainReply; page: Page }) {
  const shown = reply.choices.slice(0, MOST_WHICH)
  const more = reply.choices.length - shown.length
  return (
    <Card title="Which workflow?">
      <div className={chat['chips']}>
        {shown.map((choice) => (
          <button key={choice.use_case_id} type="button" className={chat['chip']} onClick={() => page.ask(explainAsk(choice.name))}>
            {choice.name}
          </button>
        ))}
        {more > 0 ? (
          <Link to="/workflows" className={chat['moreChoices']}>
            and {more} more
          </Link>
        ) : null}
      </div>
    </Card>
  )
}

function Missing({ looked }: { looked: string }) {
  return (
    <Card
      title="I can’t find a workflow called that."
      actions={
        <OpenButton item={{ kind: 'workflows' }} to="/workflows">
          Check my workflows
        </OpenButton>
      }
    >
      <p className="muted">I looked for “{looked}”.</p>
    </Card>
  )
}

/**
 * The workflow in the sentence its page shows, with Open the workflow. Code builds the sentence from what the platform stored, so no
 * model words it, and the chat and the page never disagree. A workflow deleted since, or one that couldn't be loaded, says so instead.
 */
function ExplainCard({ useCaseId, name }: { useCaseId: string; name: string | null }) {
  const useCase = useUseCase(useCaseId)
  const view = useCase.data
  return (
    <Card
      title={view?.name ?? name ?? 'The workflow'}
      actions={
        view ? (
          <OpenButton item={{ kind: 'workflow', id: useCaseId }} to={`/workflows/${encodeURIComponent(useCaseId)}`}>
            Open the workflow
          </OpenButton>
        ) : undefined
      }
    >
      {view ? (
        <p>{sentenceOf(view)}</p>
      ) : useCase.error instanceof ApiError && useCase.error.status === 404 ? (
        <p className="muted">That workflow isn’t here any more.</p>
      ) : useCase.isError ? (
        <p role="alert">
          The workflow could not be loaded. <Button onClick={() => void useCase.refetch()}>Try again</Button>
        </p>
      ) : (
        <p className="muted" role="status">
          Loading the workflow
        </p>
      )}
    </Card>
  )
}

interface ExplainAnswerProps {
  readonly reply: ExplainReply
  readonly focus: string | null
  readonly page: Page
}

export function ExplainAnswer({ reply, focus, page }: ExplainAnswerProps) {
  const memory = useContext(CardMemoryContext)
  const [settled] = useState(() => {
    const kept = memory.focus.kept()
    const value = kept === undefined ? focus : kept
    memory.focus.keep(value)
    return value
  })
  const answer = explainAnswerOf(reply, settled)
  if (answer.kind === 'one') return <ExplainCard useCaseId={answer.id} name={answer.name} />
  if (answer.kind === 'missing') return <Missing looked={reply.missing ?? ''} />
  return <Which reply={reply} page={page} />
}
