import type { RunView, TemplateView } from '../../api/types'
import { spineStateWords, type SpineState } from '../../ui/spineState'

export interface RunDot {
  readonly key: string
  readonly name: string
  readonly state: SpineState['kind']
  readonly words: string
}

function stateOf(run: RunView, kind: 'agent' | 'approval' | 'write_action'): SpineState {
  switch (kind) {
    case 'agent':
      if (run.state === 'pending') return { kind: 'not_reached' }
      if (run.state === 'working') return { kind: 'working' }
      if (run.state === 'failed') return run.stage === 'pending' || run.stage === 'working' ? { kind: 'failed' } : { kind: 'done' }
      return { kind: 'done' }
    case 'approval':
      if (run.state === 'awaiting_approval') return { kind: 'waiting' }
      if (run.state === 'rejected') return { kind: 'declined', by: run.rejected_by }
      if (run.state === 'acting') return { kind: 'approved', by: '' }
      if (run.state === 'succeeded') return run.outcome === 'nothing_to_write' ? { kind: 'not_needed' } : { kind: 'approved', by: run.written[0]?.approved_by.join(' and ') ?? '' }
      return { kind: 'not_reached' }
    case 'write_action':
      if (run.state === 'acting') return { kind: 'working' }
      if (run.state === 'succeeded') return run.outcome === 'nothing_to_write' ? { kind: 'not_needed' } : { kind: 'done' }
      if (run.state === 'failed' && run.stage === 'acting') return { kind: 'failed' }
      return { kind: 'not_reached' }
  }
}

/** A finished run's blocks as dots, from its view alone, for the rows under the hero. */
export function runDots(run: RunView, templates: readonly TemplateView[] | undefined): RunDot[] {
  const blocks = templates?.flatMap((template) => template.blocks) ?? []
  const byKind = [
    { key: 'agent', name: blocks.find((block) => block.kind === 'agent')?.name ?? 'Agent work', kind: 'agent' as const },
    { key: 'approval', name: blocks.find((block) => block.kind === 'approval')?.name ?? 'Approval', kind: 'approval' as const },
    { key: 'write', name: blocks.find((block) => block.kind === 'write_action')?.name ?? 'Write', kind: 'write_action' as const },
  ]
  return byKind.map((block) => {
    const state = stateOf(run, block.kind)
    return { key: block.key, name: block.name, state: state.kind, words: spineStateWords(state) }
  })
}
