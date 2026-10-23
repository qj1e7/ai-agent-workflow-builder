import { ButtonLink } from '../ui/Button'
import styles from './NotFoundPage.module.css'

export function NotFoundPage() {
  return (
    <div className={`page ${styles['page']}`}>
      <h1>We could not find that page</h1>
      <p className="muted">The address may be wrong, or the page may have moved.</p>
      <ButtonLink to="/" variant="primary">
        Go to the runs
      </ButtonLink>
    </div>
  )
}
