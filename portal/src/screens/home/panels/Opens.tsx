import { useMemo, type ReactNode } from 'react'
import { OpensInPanel, type PanelItem } from '../../../ui/sidePanel'

/** Inside a list in the panel, an item opens in the panel, with Back to the list. Anything opened from that item goes to its page. */
export function OpensBeside({ shown, onOpen, children }: { shown: PanelItem; onOpen: (item: PanelItem) => void; children: ReactNode }) {
  const opener = useMemo(() => ({ shown, open: (item: PanelItem) => onOpen(item), show: onOpen }), [shown, onOpen])
  return <OpensInPanel.Provider value={opener}>{children}</OpensInPanel.Provider>
}
