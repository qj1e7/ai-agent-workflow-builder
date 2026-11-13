import { groupOf, openPathOf, wordsOf, type Need, type NeedGroup } from '../home/home'
import { runWhen } from './times'

export interface NeedRow {
  readonly key: string
  readonly group: NeedGroup
  /** Red for what has stopped or can't work, amber for what waits on a person. */
  readonly tone: 'err' | 'wait'
  /** The workflow or software the row is about, said in bold first. Null when the sentence names its own subject. */
  readonly subject: string | null
  readonly rest: string
  readonly to: string
}

const SOFTWARE_PAGE = '/software'

/** "at 8:00" for a time today, "Tue 3 Nov at 10:14" for an earlier day. */
function atWords(iso: string, now: Date): string {
  return runWhen(iso, now).replace(/^Today, /, 'at ').replace(/^(.+), (\d+:\d+)$/, '$1 at $2')
}

const oneLine = (words: string): string => (words.split(/(?<=\.)\s/)[0] ?? words).replace(/\.$/, '')

/**
 * A Need as the sketch draws it on Workflows: one line, the subject in bold, a colour for how urgent, and the page it opens.
 * A software that moved opens its own page, not the old list row.
 */
export function needRow(need: Need, now: Date): NeedRow {
  const base = { key: need.key, group: groupOf(need), to: openPathOf(need) }
  switch (need.kind) {
    case 'stopped':
      return { ...base, tone: 'err', subject: need.item.use_case_name, rest: `stopped ${atWords(need.item.stopped_at, now)}` }
    case 'approval':
      return { ...base, tone: 'wait', subject: need.item.use_case_name, rest: 'needs your yes' }
    case 'address':
      return {
        ...base,
        tone: 'err',
        to: `${SOFTWARE_PAGE}/${need.item.software_id}`,
        subject: need.item.name,
        rest: need.item.moved_to ? 'moved on GitHub' : 'can’t be found on GitHub',
      }
    default: {
      const words = wordsOf(need, now)
      return { ...base, tone: words.tone === 'bad' ? 'err' : 'wait', subject: null, rest: oneLine(words.title) }
    }
  }
}
