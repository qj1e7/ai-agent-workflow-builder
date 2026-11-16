import { useContext, useState } from 'react'
import { Link } from '../../ui/Link'
import type { ExplainReply } from '../../api/types'
import { useExplain } from '../../api/workflowQueries'
import { Card } from '../../ui/Card'
import { OpenButton } from '../../ui/OpenItem'
import type { Page } from '../home/AnswerCards'
import { CardMemoryContext } from '../home/cardMemory'
import chat from '../home/Planner.module.css'
import { Explained } from './Explained'
import { explainAnswerOf, explainAsk, explainStateOf } from './explain'
import { Report } from './Report'

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

/** The workflow's report, asked for with the reworded In short. The sections are always code's words. */
function ExplainCard({ useCaseId, name }: { useCaseId: string; name: string | null }) {
  const memory = useContext(CardMemoryContext)
  const [code, setCode] = useState(() => memory.wording.kept() ?? false)
  const query = useExplain(useCaseId, { reworded: true })
  const state = explainStateOf(query)
  const swap = () => {
    memory.wording.keep(!code)
    setCode(!code)
  }
  return (
    <Card
      title={state.kind === 'report' ? state.report.name : (name ?? 'The workflow')}
      actions={
        state.kind === 'report' ? (
          <OpenButton item={{ kind: 'workflow', id: useCaseId }} to={`/workflows/${encodeURIComponent(useCaseId)}`}>
            Open the workflow
          </OpenButton>
        ) : undefined
      }
    >
      <Explained state={state} retry={() => void query.refetch()}>
        {(report) => <Report report={report} code={code} onWording={swap} />}
      </Explained>
    </Card>
  )
}

interface ExplainAnswerProps {
  readonly reply: ExplainReply
  readonly typed: string
  readonly focus: string | null
  readonly page: Page
}

export function ExplainAnswer({ reply, typed, focus, page }: ExplainAnswerProps) {
  const memory = useContext(CardMemoryContext)
  const [settled] = useState(() => {
    const kept = memory.focus.kept()
    const value = kept === undefined ? focus : kept
    memory.focus.keep(value)
    return value
  })
  const answer = explainAnswerOf(reply, typed, settled)
  if (answer.kind === 'one') return <ExplainCard useCaseId={answer.id} name={answer.name} />
  if (answer.kind === 'missing') return <Missing looked={reply.missing ?? ''} />
  return <Which reply={reply} page={page} />
}
