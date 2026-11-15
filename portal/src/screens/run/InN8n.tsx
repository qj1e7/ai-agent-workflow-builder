import { useRunInN8n } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { Canvas } from '../../ui/Canvas'
import { runCanvasOf } from './n8nStates'

const NO_COPY = 'The platform has no copy of the n8n workflow this run used.'

interface RunInN8nProps {
  readonly runId: string
  /** The workflow's name, which names the picture. */
  readonly name: string
  /** The newest event the page shows. Each new one reads the blocks' states again. */
  readonly seq: number
  readonly ended: boolean
}

/** The run page's In n8n tab: the version the run used, drawn as n8n draws it, each block taking the run's state as it goes. */
export function RunInN8n({ runId, name, seq, ended }: RunInN8nProps) {
  const run = useRunInN8n(runId, seq, ended)
  if (!run.data) {
    return run.isError ? (
      <p>
        The run in n8n could not be loaded. <Button onClick={() => void run.refetch()}>Try again</Button>
      </p>
    ) : (
      <p className="muted" role="status">
        Loading the run in n8n
      </p>
    )
  }
  if (run.data.blocks.length === 0) return <p>{NO_COPY}</p>
  const canvas = runCanvasOf(run.data)
  return <Canvas blocks={run.data.blocks} name={name} nodes={canvas.nodes} edges={canvas.edges} />
}
