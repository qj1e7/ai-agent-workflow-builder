import { useSearchParams } from 'react-router'
import { useMe, useModelSettings } from '../../api/queries'
import { useConfirmations } from '../../api/settingsQueries'
import { ModelTab } from './ModelTab'
import { PeopleTab } from './PeopleTab'
import { canChangeSettings, needsYou, SETTINGS_TABS, tabFrom, type SettingsTab } from './settings'
import styles from './Settings.module.css'

function useNeedsAttention(): Record<SettingsTab, boolean> {
  const me = useMe().data
  const model = useModelSettings().data
  const confirmations = useConfirmations().data
  const noModel = model !== undefined && model.available && model.active === null && canChangeSettings(me)
  return {
    model: noModel || (model?.pending?.you_can_decide ?? false),
    people: needsYou(confirmations, 'approver'),
  }
}

export function SettingsTabs() {
  const [params, setParams] = useSearchParams()
  const tab = tabFrom(params.get('tab'))
  const me = useMe().data
  const attention = useNeedsAttention()
  return (
    <>
      <div className={styles['tabs']} role="group" aria-label="Settings sections">
        {SETTINGS_TABS.map(({ id, label }) => (
          <button key={id} type="button" aria-pressed={tab === id} onClick={() => setParams(id === 'model' ? {} : { tab: id }, { replace: true })}>
            {label}
            {attention[id] ? (
              <>
                <span className={styles['dot']} aria-hidden="true" />
                <span className="visually-hidden"> (needs you)</span>
              </>
            ) : null}
          </button>
        ))}
      </div>
      {tab === 'model' ? <ModelTab /> : <PeopleTab me={me} />}
    </>
  )
}

export default SettingsTabs
