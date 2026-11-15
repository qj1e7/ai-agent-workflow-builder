import created from '@contracts/fixtures/builder/agent-use-case.off.created.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { N8nBlockView } from '../api/types'
import { Canvas } from './Canvas'
import { edgeKey, type NodeState } from './canvasLayout'

const BLOCKS = created.blocks as N8nBlockView[]

/** Each block's state by its name, as drawn: a block's group carries its state, and its label follows inside it. */
const statesIn = (html: string) => new Map([...html.matchAll(/<g class="_node_[^"]*" data-state="(\w+)"[\s\S]*?class="_label_[^"]*"[^>]*>([^<]*)</g)].map((m) => [m[2], m[1]]))
const stateOf = (html: string, name: string) => statesIn(html).get(name)
const title = (html: string) => /<title[^>]*>([^<]*)<\/title>/.exec(html)?.[1] ?? ''

describe('the canvas in each state a run gives a block', () => {
  const states: Record<string, NodeState> = { 'Read release': 'ok', Compare: 'ok', 'Newer?': 'ok', 'Ask for a yes': 'wait', 'Create ticket': 'err', 'Start from the Portal': 'now' }
  const html = renderToStaticMarkup(<Canvas blocks={BLOCKS} name="LangGraph release check" nodes={states} edges={{ [edgeKey('Read release', 'Compare')]: 'ok', [edgeKey('Newer?', 'Ask for a yes')]: 'flow' }} />)

  it('marks every block with its state, and a block with no state as idle', () => {
    expect(stateOf(html, 'Read release')).toBe('ok')
    expect(stateOf(html, 'Start from the Portal')).toBe('now')
    expect(stateOf(html, 'Ask for a yes')).toBe('wait')
    expect(stateOf(html, 'Create ticket')).toBe('err')
    expect(stateOf(html, 'Mon 8:00')).toBe('idle')
  })

  it('says each run state in words after the block’s name, so the picture is not colour alone', () => {
    expect(title(html)).toBe(
      'LangGraph release check in n8n: Mon 8:00, Start from the Portal (working), Read release (done), Compare (done), Newer? (done), Ask for a yes (waiting), Create ticket (stopped here), Nothing to change',
    )
  })

  it('draws the ways out in the states it is given', () => {
    expect(html).toContain('data-state="flow"')
    expect(html.match(/class="[^"]*edge[^"]*" data-state="ok"/g)).toHaveLength(1)
  })

  it('names one of n8n’s data blocks an n8n block, and a block that is off “Not allowed”, as the sketch does', () => {
    const shaped = renderToStaticMarkup(<Canvas blocks={[...BLOCKS, { name: 'Keep fields', kind: 'other', badge: 'n8n', next: [] }]} name="x" />)
    expect(shaped).toContain('n8n block')
    expect(shaped).not.toContain('Not allowed')
    const off = renderToStaticMarkup(<Canvas blocks={[...BLOCKS, { name: 'Send it', kind: 'off', badge: 'n8n', next: [] }]} name="x" />)
    expect(off).toMatch(/>Send it<\/text><text[^>]*>Not allowed</)
  })

  it('names what one of n8n’s own blocks does by its tag, without our badge (ADR 0045)', () => {
    const posts = renderToStaticMarkup(<Canvas blocks={[...BLOCKS, { name: 'Tell Slack', kind: 'other', badge: 'n8n', tag: 'Posts in Slack', next: [] }]} name="x" />)
    expect(posts).toMatch(/>Tell Slack<\/text><text[^>]*>Posts in Slack</)
    expect(posts).not.toMatch(/>Our block<\/text>(?:(?!<g class="_node_)[\s\S])*>Tell Slack</)
  })

  it('marks a block it waits at with a shape as well as amber, as it marks a stop and a tick', () => {
    const waitingAt = /<g class="_node_[^"]*" data-state="wait"[\s\S]*?<g class="_waiting_/
    expect(html).toMatch(waitingAt)
  })
})
