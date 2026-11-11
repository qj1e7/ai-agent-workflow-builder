import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router'
import { PageHead } from '../../shell/PageHead'
import styles from './SettingsPage.module.css'

const SettingsTabs = lazy(() => import('./SettingsTabs'))

export function SettingsPage({ heading, lead, now }: { heading: string; lead: string; now: Date }) {
  // An agent opened from a link takes focus in its own dialog, so the heading doesn't.
  const agentOpen = useSearchParams()[0].get('agent') !== null
  return (
    <div className={styles['page']}>
      <PageHead heading={heading} lead={lead} movesFocus={agentOpen} />
      <Suspense
        fallback={
          <p className="muted" role="status">
            Loading
          </p>
        }
      >
        <SettingsTabs now={now} />
      </Suspense>
    </div>
  )
}
