/** A view transition: it runs `update` a frame later, once the browser has kept a picture of the screen as it was. */
export type Transition = (update: () => void) => void

/**
 * Sends a message, folding the hero into the chat first when a transition is given. The browser runs the fold a frame later, so until
 * then `hold` keeps the box and chips still and any other Enter or chip press is ignored: one message at a time, in the order sent.
 * Returns whether this press sent, or will send once the fold runs.
 */
export function foldSender(hold: (on: boolean) => void): (go: () => void, transition: Transition | null) => boolean {
  let waiting = false
  return (go, transition) => {
    if (waiting) return false
    if (transition === null) {
      go()
      return true
    }
    waiting = true
    hold(true)
    transition(() => {
      waiting = false
      hold(false)
      go()
    })
    return true
  }
}
