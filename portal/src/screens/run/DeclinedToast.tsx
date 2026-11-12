import { useState } from 'react'
import { Toast } from '../../ui/Toast'
import type { Declined } from './runModel'
import { declinedNowWords } from './words'

/** Right after this person declines, the record as a message at the bottom of the page, as the prototype's Decline gives it. */
export function DeclinedToast({ declined }: { declined: Declined | null }) {
  const [readBy, setReadBy] = useState<string | null>(null)
  const message = declined && declined.by !== readBy ? { id: 1, text: declinedNowWords(declined) } : null
  return <Toast message={message} onDismiss={() => setReadBy(declined?.by ?? null)} />
}
