import { connectorLabel } from '../../api/labels'
import type { DecidedReply, PastDecisionView } from '../../api/types'
import { count, declineTail, type NameOf } from '../run/words'
import { runWhen } from '../workflows/times'

type Only = DecidedReply['only']

const ONLY_WORDS = { approve: 'approved', decline: 'declined' } as const

/** "Here are your 2 decisions.", or for a question about declines alone, "You haven’t declined any requests yet." */
export function decidedSay(total: number, shown: number, only: Only): string {
  const said =
    only === null
      ? total === 0
        ? 'You haven’t decided on any requests yet.'
        : total === 1
          ? 'Here is your decision.'
          : `Here are your ${String(total)} decisions.`
      : total === 0
        ? `You haven’t ${ONLY_WORDS[only]} any requests yet.`
        : `You ${ONLY_WORDS[only]} ${count(total, 'request')}.`
  return shown < total ? `${said} The ${String(shown)} newest are here.` : said
}

/** " at 9:10 today", or ", Mon 26 Oct, 8:00", after "Approved by Bob". */
function decidedAt(at: string, now: Date): string {
  const when = runWhen(at, now)
  return when.startsWith('Today, ') ? ` at ${when.slice('Today, '.length)} today` : `, ${when}`
}

/** What the run did after a yes, in the words its run page and the Workflows row use. */
function afterYes(decision: PastDecisionView, nameOf: NameOf): string {
  const noun = decision.tickets ? 'ticket' : 'change'
  switch (decision.run_state) {
    case 'succeeded':
      if (decision.written === 0) return 'Nothing new to write.'
      return `${count(decision.written, noun)} ${decision.tickets ? 'created' : 'written'}${decision.connector ? ` in ${connectorLabel(decision.connector)}` : ''}.`
    case 'awaiting_approval':
      return 'It waits for the next yes.'
    case 'rejected':
      return decision.declined_by ? `Then declined by ${nameOf(decision.declined_by)}. ${declineTail({ reason: null })}` : declineTail({ reason: null })
    case 'failed':
      return 'The run stopped.'
    case 'skipped':
      return 'An earlier run is still waiting for a yes.'
    case 'expired':
      return 'Then no answer. Nothing was written.'
    case 'lost':
      return 'n8n lost the run. Nothing was written.'
    case 'acting':
      return 'Writing what was approved.'
    case 'pending':
    case 'working':
    case 'proposed':
      return 'Running now.'
  }
}

/**
 * One decision in a line, as the run page and Teams say it: "Approved by Bob, Mon 26 Oct, 8:00. 1 ticket created in Jira.", or the
 * declined record with when, "Declined by Bob at 9:10 today. Nothing was written. Reason: Wrong version."
 */
export function decisionLine(decision: PastDecisionView, me: string, now: Date, nameOf: NameOf): string {
  const at = decidedAt(decision.at, now)
  const who = nameOf(me)
  if (decision.verdict === 'approve') return `Approved by ${who}${at}. ${afterYes(decision, nameOf)}`
  const before = decision.approved_before.map(nameOf)
  const head = before.length > 0 ? `Approved by ${before.join(', then ')}, then declined by ${who}${at}` : `Declined by ${who}${at}`
  return `${head}. ${declineTail({ reason: decision.reason })}`
}
