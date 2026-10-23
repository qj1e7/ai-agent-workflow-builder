import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useCreateUseCase, useStartRun } from '../../api/queries'
import type { TemplateView } from '../../api/types'
import { createBody, EXAMPLE_TASK, exampleParams } from '../builder/plan'

export type FirstRunState = { readonly is: 'idle' } | { readonly is: 'starting' } | { readonly is: 'failed'; readonly message: string }

export interface FirstRun {
  readonly state: FirstRunState
  start(this: void): void
}

/**
 * One click: save the template's own example as a use case, then start a run of it. On success nothing
 * more happens here. useStartRun invalidates the runs query, the overview refetches, and the hero takes
 * the stage with the live run. The state stays 'starting' until then, so a second click cannot start another.
 */
export function useFirstRun(template: TemplateView): FirstRun {
  const create = useCreateUseCase()
  const run = useStartRun()
  const explain = useErrorWords()
  const state = stateOf(create, run, explain)

  function start(): void {
    if (state.is === 'starting') return
    create.mutate(createBody(template, EXAMPLE_TASK, { name: template.name, params: exampleParams(template) }), {
      onSuccess: (created) => run.mutate({ useCaseId: created.use_case_id, idempotencyKey: newIdempotencyKey() }),
    })
  }

  return { state, start }
}

function stateOf(
  create: ReturnType<typeof useCreateUseCase>,
  run: ReturnType<typeof useStartRun>,
  explain: (error: unknown) => string,
): FirstRunState {
  if (create.isPending || run.isPending || run.isSuccess) return { is: 'starting' }
  if (create.isError) return { is: 'failed', message: explain(create.error) }
  if (run.isError) return { is: 'failed', message: explain(run.error) }
  return { is: 'idle' }
}
