import { StatePill } from '../../ui/State'
import { YOUR_YES } from './approvalWords'
import { runPill, STATE_TONE, type StageFacts } from './words'

/**
 * The run's one state pill, the same on the card, the panel and the page, and the same words as a list's row. `yours` is set on the
 * run page while the reader may say yes, so its one pill says the request needs their yes.
 */
export function RunPill({ facts, yours = false }: { facts: StageFacts; yours?: boolean }) {
  const { label, tone } = yours ? YOUR_YES : runPill(facts)
  return (
    <StatePill tone={STATE_TONE[tone]} data-run-pill="">
      {label}
    </StatePill>
  )
}
