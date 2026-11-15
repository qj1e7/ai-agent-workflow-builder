import { useContext, useEffect } from 'react'
import { NARROW, useMediaQuery } from '../../ui/media'
import { OpensInPanel, type PanelItem } from '../../ui/sidePanel'
import { CardMemoryContext } from './cardMemory'
import { CardLive } from './primary'

/**
 * On a wide screen the newest answer about one run or one request shows it beside the chat at once, as the sketch does. On a
 * narrow screen only the card shows, and its Open opens the panel. It happens once for an answer, when the answer arrives, and
 * does not move focus. A later visit to the chat, or a person who closed the panel, is never overruled.
 */
export function useShowBesideOnWide(item: PanelItem | null): void {
  const opener = useContext(OpensInPanel)
  const memory = useContext(CardMemoryContext)
  const newest = useContext(CardLive)
  const narrow = useMediaQuery(NARROW)
  useEffect(() => {
    if (!opener || !item || !newest || memory.beside.kept()) return
    memory.beside.keep(true)
    if (!narrow) opener.show(item)
  }, [opener, item, newest, narrow, memory])
}
