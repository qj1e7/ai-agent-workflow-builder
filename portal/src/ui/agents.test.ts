import { describe, expect, it } from 'vitest'
import { agentIdentity, KNOWN_AGENT_IDS } from './agents'
import { personTone } from './personTone'

describe('agentIdentity', () => {
  it('gives the three known agents their names and accessories', () => {
    expect(KNOWN_AGENT_IDS).toEqual(['room_lead', 'release_checker', 'troubleshooter'])
    expect(agentIdentity('room_lead')).toMatchObject({ name: 'Room lead', accessory: 'headset', hue: 'var(--lead)', tint: 'var(--lead-tint)' })
    expect(agentIdentity('release_checker')).toMatchObject({ name: 'Release checker', accessory: 'magnifier', hue: 'var(--checker)' })
    expect(agentIdentity('troubleshooter')).toMatchObject({ name: 'AI troubleshooter', accessory: 'wrench', hue: 'var(--trouble)' })
  })

  it('keeps a known agent its own name whatever the event calls it', () => {
    expect(agentIdentity('room_lead', 'Someone else').name).toBe('Room lead')
  })

  it('gives an unknown agent a plain face and a name from the event, or from its id', () => {
    expect(agentIdentity('patch_planner', 'Patch planner')).toMatchObject({ id: 'patch_planner', name: 'Patch planner', accessory: 'none' })
    expect(agentIdentity('patch_planner').name).toBe('Patch planner')
    expect(agentIdentity('access_auditor').name).toBe('Access auditor')
  })

  it('gives an unknown agent the same colours every time, whatever name it is shown under', () => {
    const first = agentIdentity('security_reviewer')
    const second = agentIdentity('security_reviewer', 'Security reviewer')
    expect([second.hue, second.tint]).toEqual([first.hue, first.tint])
  })

  it('keeps the colours an unknown agent has today, so a hash change does not recolour agents people know', () => {
    expect(agentIdentity('security_reviewer')).toMatchObject({ hue: 'var(--agent-2)', tint: 'var(--agent-2-tint)' })
    expect(agentIdentity('patch_planner')).toMatchObject({ hue: 'var(--agent-1)', tint: 'var(--agent-1-tint)' })
  })

  it('uses all four colour pairs across many ids, and always a hue with its own tint', () => {
    const seen = new Set<string>()
    for (let index = 0; index < 200; index += 1) {
      const { hue, tint } = agentIdentity(`agent_${index}`)
      expect(tint).toBe(hue.replace(')', '-tint)'))
      seen.add(hue)
    }
    expect([...seen].sort()).toEqual(['var(--agent-1)', 'var(--agent-2)', 'var(--agent-3)', 'var(--agent-4)'])
  })
})

describe('personTone', () => {
  it('gives a name the same tone every time', () => {
    expect(personTone('Alice')).toEqual(personTone('Alice'))
  })

  it("draws the seeded users in the template's colours: Alice peach (person-1), Bob blue (person-2)", () => {
    expect(personTone('Alice')).toEqual({ bg: 'var(--person-1-bg)', ink: 'var(--person-1-ink)' })
    expect(personTone('Bob')).toEqual({ bg: 'var(--person-2-bg)', ink: 'var(--person-2-ink)' })
  })

  it('uses all four tones across many names', () => {
    const seen = new Set(Array.from({ length: 200 }, (_, index) => personTone(`person ${index}`).bg))
    expect(seen.size).toBe(4)
  })
})
