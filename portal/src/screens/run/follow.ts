import { useEffect } from 'react'

export const POLL_FAILED_MS = 10_000

/** After a failure the stream may close. When the run has moved on without it, as after a retry, reconnect now. */
export function useReconnectWhenBehind(behind: boolean, restart: () => void): void {
  useEffect(() => {
    if (behind) restart()
  }, [behind, restart])
}
