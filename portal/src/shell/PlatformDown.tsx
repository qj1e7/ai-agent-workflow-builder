import { ApiError } from '../api/client'
import { Button } from '../ui/Button'
import { PageHead } from './PageHead'

/** A network failure, or the platform answering that it is not well. A 4xx is a different problem and is not called "down". */
export function platformIsDown(error: unknown): boolean {
  return error instanceof ApiError ? error.status >= 500 : true
}

export function PlatformDown({ onRetry }: { onRetry: () => void }) {
  return (
    <>
      <PageHead heading="We can't reach the platform" lead="Check your connection, or try again in a moment." />
      <Button variant="primary" onClick={onRetry}>
        Try again
      </Button>
    </>
  )
}
