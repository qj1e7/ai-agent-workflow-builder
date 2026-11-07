import { describe, expect, it } from 'vitest'
import capabilitiesFixture from '../../../../contracts/fixtures/planner/capabilities.json'
import connectionsFixture from '../../../../contracts/fixtures/settings/connections.json'
import type { CapabilitiesView, CapabilityView, ConnectionOut } from '../../api/types'
import { settingsPathFor } from './capabilities'

const LINES = (capabilitiesFixture as unknown as CapabilitiesView).capabilities
const line = (connection: CapabilityView['connection'], needsModel: boolean): CapabilityView => ({ ...LINES[0]!, connection, needs_model: needsModel })
const connections = (states: Record<string, ConnectionOut['state']>): ConnectionOut[] =>
  (connectionsFixture.connections as unknown as ConnectionOut[]).map((c) => ({ ...c, state: states[c.id] ?? 'working' }))

describe('the Settings tab that holds a line’s fix', () => {
  it('is the AI model tab when the model is what is missing, even for a line that also uses Jira', () => {
    expect(settingsPathFor(line('jira', true), connections({ model: 'not_set_up' }))).toBe('/settings?tab=model')
    expect(settingsPathFor(line(null, true))).toBe('/settings?tab=model')
  })

  it('is Connections when the line’s own connection is what is broken, whatever the model says', () => {
    expect(settingsPathFor(line('jira', true), connections({ jira: 'not_answering', model: 'not_set_up' }))).toBe('/settings?tab=connections')
    expect(settingsPathFor(line('jira', false), connections({ jira: 'not_answering' }))).toBe('/settings?tab=connections')
    expect(settingsPathFor(line('jira', true))).toBe('/settings?tab=connections')
  })
})
