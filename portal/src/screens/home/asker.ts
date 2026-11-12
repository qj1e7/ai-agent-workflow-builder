import { isOperator } from '../../api/me'
import { useMe } from '../../api/queries'
import type { Asker } from './answers'

/** Who is asking. Until the person is known, an answer is drawn as for an Operator: the server still refuses anyone else every change. */
export function useAsker(): Asker {
  const me = useMe().data
  return me === undefined || isOperator(me) ? 'operator' : 'approver'
}
