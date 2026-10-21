import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Avatar, type AvatarProps } from './Avatar'

const faces: AvatarProps[] = [
  { kind: 'agent', agentId: 'room_lead' },
  { kind: 'agent', agentId: 'release_checker' },
  { kind: 'agent', agentId: 'troubleshooter' },
  { kind: 'agent', agentId: 'patch_planner' },
]
const all: AvatarProps[] = [...faces, { kind: 'safety_checker' }, { kind: 'person', name: 'Bob' }, { kind: 'empty_seat' }]

const markup = (props: AvatarProps) => renderToStaticMarkup(createElement(Avatar, props))

describe('Avatar', () => {
  it('draws every colour from a token, so a theme change reaches it', () => {
    for (const props of all) expect(markup(props), props.kind).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i)
  })

  it('draws the faces without an inline style, which the Content Security Policy refuses', () => {
    for (const props of faces) expect(markup(props), props.kind).not.toContain('style=')
  })

  it('draws an agent as a round head with two eyes, and only a known agent gets an accessory', () => {
    const eyes = (props: AvatarProps) => markup(props).match(/<rect[^>]*rx="2"[^>]*fill="var\(--face-ink\)"/g)?.length
    for (const props of faces) expect(eyes(props), JSON.stringify(props)).toBe(2)
    expect(markup({ kind: 'agent', agentId: 'room_lead' })).toContain('stroke="var(--lead)"')
    expect(markup({ kind: 'agent', agentId: 'release_checker' })).toContain('stroke="var(--checker)"')
    expect(markup({ kind: 'agent', agentId: 'troubleshooter' })).toContain('fill="var(--trouble)"')
    expect(markup({ kind: 'agent', agentId: 'patch_planner' })).not.toMatch(/stroke="var\(--agent-\d\)"|<g /)
  })

  it('draws a person as their initial, upper case', () => {
    expect(markup({ kind: 'person', name: ' bob ' })).toContain('>B<')
  })

  it('sizes an agent face by the size prop', () => {
    expect(markup({ kind: 'agent', agentId: 'room_lead', size: 28 })).toContain('width="28"')
  })
})
