import { useNavigate } from 'react-router'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useStartRun } from '../../api/queries'

export interface RunNow {
  start: (useCaseId: string) => void
  isStarting: (useCaseId: string) => boolean
  anyStarting: boolean
  errorFor: (useCaseId: string) => string | null
}

export function useRunNow(): RunNow {
  const explain = useErrorWords()
  const navigate = useNavigate()
  const mutation = useStartRun()

  return {
    start: (useCaseId) =>
      mutation.mutate(
        { useCaseId, idempotencyKey: newIdempotencyKey() },
        { onSuccess: (started) => void navigate(`/runs/${started.run_id}`) },
      ),
    isStarting: (useCaseId) => mutation.isPending && mutation.variables.useCaseId === useCaseId,
    anyStarting: mutation.isPending,
    errorFor: (useCaseId) =>
      mutation.isError && mutation.variables.useCaseId === useCaseId ? explain(mutation.error) : null,
  }
}
