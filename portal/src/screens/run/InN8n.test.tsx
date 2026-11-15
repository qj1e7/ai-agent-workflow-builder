import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ended from '../../../../contracts/fixtures/builder/run.n8n.ended.json'
import waiting from '../../../../contracts/fixtures/builder/run.n8n.waiting.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { RunN8nView } from '../../api/types'
import { RunInN8n } from './InN8n'

const WAITING = waiting as RunN8nView
const ENDED = ended as RunN8nView
const SEQ = 7

function render(view: RunN8nView | null): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  if (view) queryClient.setQueryData(['run', session.cacheScope(), view.run_id, 'n8n', SEQ], view)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <RunInN8n runId={WAITING.run_id} name="LangGraph release check" seq={SEQ} ended={false} />
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const title = (html: string) => /<title[^>]*>([^<]*)<\/title>/.exec(html)?.[1] ?? ''
const drawn = (html: string) => new Map([...html.matchAll(/<g class="_node_[^"]*" data-state="(\w+)"[\s\S]*?class="_label_[^"]*"[^>]*>([^<]*)</g)].map((m) => [m[2], m[1]]))

describe('the run page’s In n8n tab', () => {
  it('draws a run waiting at the yes: the blocks it passed ticked, the yes amber, the write not run', () => {
    const html = render(WAITING)
    expect(Object.fromEntries(drawn(html))).toMatchObject({ 'Read release': 'ok', Compare: 'ok', 'Newer?': 'ok', 'Ask for a yes': 'wait', 'Create ticket': 'idle', 'Mon 8:00': 'idle' })
    expect(title(html)).toContain('Newer? (done), Ask for a yes (waiting), Create ticket,')
  })

  it('draws where an ended run stopped, red with its mark', () => {
    const html = render({ ...ENDED, run_id: WAITING.run_id })
    expect(drawn(html).get('Create ticket')).toBe('err')
    expect(title(html)).toContain('Create ticket (stopped here)')
  })

  it('draws the block at work with dashes flowing into it', () => {
    const html = render({ ...WAITING, states: { 'Read release': 'done', Compare: 'running' } })
    expect(drawn(html).get('Compare')).toBe('now')
    expect(html.match(/data-state="flow"/g)).toHaveLength(1)
  })

  it('says it is loading, and says so plainly when the platform kept no copy of the version the run used', () => {
    expect(render(null)).toContain('Loading the run in n8n')
    expect(render({ ...WAITING, blocks: [] })).toContain('The platform has no copy of the n8n workflow this run used.')
  })
})
