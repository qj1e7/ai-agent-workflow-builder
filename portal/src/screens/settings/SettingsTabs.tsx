import { useSearchParams } from 'react-router'
import { useMe, useModelSettings } from '../../api/queries'
import { useConnections } from '../../api/capabilityQueries'
import { useConfirmations } from '../../api/settingsQueries'
import { ConnectionsTab } from './ConnectionsTab'
import { connectionNeedsYou } from './connections'
import { ModelTab } from './ModelTab'
import { PeopleTab } from './PeopleTab'
import { modelNeedsYou, needsYou, SETTINGS_TABS, tabFrom, type SettingsTab } from './settings'
import styles from './Settings.module.css'

function useNeedsAttention(): Record<SettingsTab, boolean> {
  const me = useMe().data
  const model = useModelSettings().data
  const confirmations = useConfirmations().data
  const connections = useConnections().data
  return {
    connections: connectionNeedsYou(connections?.connections),
    model: modelNeedsYou(model, me),
    people: needsYou(confirmations, 'approver'),
  }
}

export function SettingsTabs({ now = new Date() }: { now?: Date }) {
  const [params, setParams] = useSearchParams()
  const tab = tabFrom(params.get('tab'))
  const me = useMe().data
  const attention = useNeedsAttention()
  return (
    <>
      <div className={styles['tabs']} role="group" aria-label="Settings sections">
        {SETTINGS_TABS.map(({ id, label }) => (
          <button key={id} type="button" aria-pressed={tab === id} onClick={() => setParams(id === 'connections' ? {} : { tab: id }, { replace: true })}>
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
      {tab === 'connections' ? <ConnectionsTab now={now} /> : tab === 'model' ? <ModelTab /> : <PeopleTab me={me} />}
    </>
  )
}

export default SettingsTabs
