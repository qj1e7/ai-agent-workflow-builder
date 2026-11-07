import { lazy, Suspense } from 'react'
import { PageHead } from '../../shell/PageHead'
import styles from './SettingsPage.module.css'

const SettingsTabs = lazy(() => import('./SettingsTabs'))

export function SettingsPage({ heading, lead, now }: { heading: string; lead: string; now: Date }) {
  return (
    <div className={styles['page']}>
      <PageHead heading={heading} lead={lead} />
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
