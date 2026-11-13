import { Link } from '../../../ui/Link'
import { useAsker } from '../asker'
import { moreWords, SEE_ALL_WORDS, type Needs } from '../home'
import styles from '../Planner.module.css'

/**
 * What follows Needs you's rows when some aren’t shown. An Operator gets the link to Workflows. Workflows lists no more for
 * someone who isn’t an Operator, so they are told how many are left instead, as their Home does.
 */
export function NeedsMore({ needs }: { needs: Needs }) {
  const asker = useAsker()
  const said = asker === 'approver' ? moreWords(needs.more) : null
  if (said !== null) return <p className={styles['more']}>{said}</p>
  if (needs.total - needs.shown.length > 0 && asker === 'operator') {
    return (
      <p className={styles['more']}>
        <Link to="/workflows">{SEE_ALL_WORDS}</Link>
      </p>
    )
  }
  return null
}
