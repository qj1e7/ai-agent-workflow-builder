import { useState, type ReactNode } from 'react'
import { useUseCase } from '../../api/queries'
import { Button } from '../../ui/Button'
import type { SimilarWorkflow } from '../../api/types'
import { Card } from '../../ui/Card'
import { OpenButton } from '../../ui/OpenItem'
import { repeatWords } from '../software/software'
import { StatusPills } from '../workflows/Status'
import { pillOf, workflowPath } from '../workflows/workflow'
import { useMainButton } from './primary'

/**
 * The sketch's already-have card: she asked for a workflow she already has, by its name, so the answer leads with that workflow and
 * Open it. The platform matches by name only, so Set up another still sets up the one she asked for, never a dead end. What the
 * workflow does and when are read from it as the platform holds it now.
 */
export function AlreadyHave({ similar, card }: { similar: SimilarWorkflow; card: ReactNode }) {
  const [another, setAnother] = useState(false)
  const main = useMainButton()
  const useCase = useUseCase(similar.use_case_id).data
  if (another) return card
  const repo = useCase?.agents.flatMap((agent) => Object.entries(agent.values)).find(([input]) => /github/i.test(input))?.[1]
  const when = useCase?.schedule ? repeatWords(useCase.schedule) : 'when an Operator starts it'
  const runs = useCase ? (repo ? `It already watches ${repo}, ${when}.` : `It already runs ${when}.`) : null
  return (
    <Card
      title={useCase?.name ?? similar.name}
      pill={useCase ? <StatusPills state={useCase.state} fact={useCase.last_run ? pillOf(useCase.last_run) : null} /> : undefined}
      actions={
        <>
          <Button onClick={() => setAnother(true)}>Set up another</Button>
          <OpenButton variant={main} item={{ kind: 'workflow', id: similar.use_case_id }} to={useCase ? workflowPath(useCase) : `/workflows/${encodeURIComponent(similar.use_case_id)}`}>
            Open it
          </OpenButton>
        </>
      }
    >
      {runs ? <p>{runs}</p> : null}
    </Card>
  )
}
