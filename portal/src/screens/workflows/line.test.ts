import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import type { UseCaseView } from '../../api/types'
import { templateLine } from './line'

const AGENTS = agentUseCase as UseCaseView
const EVERY_DAY = { day: 'every_day', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } as const

describe('the workflow’s own line, the run line before any run', () => {
  it('draws the workflow’s steps with a tag under each, as the sketch does', () => {
    const line = templateLine({ ...AGENTS, schedule: EVERY_DAY })
    expect(line.map((step) => [step.label, step.under])).toEqual([
      ['Daily 8:00', { kind: 'note', text: 'No system access' }],
      ['Check release', { kind: 'note', text: 'Reads only' }],
      ['Ask for a yes', { kind: 'note', text: 'Waits for a yes' }],
      ['Create Jira tickets', { kind: 'note', text: 'Writes after a yes' }],
    ])
  })

  it('names the start Run now while the workflow has no schedule, and never guesses a time', () => {
    expect(templateLine(AGENTS)[0]?.label).toBe('Run now')
  })

  it('shows every step as not reached yet, since no run is going', () => {
    expect(new Set(templateLine(AGENTS).map((step) => step.state))).toEqual(new Set(['todo']))
  })

  it('puts the agent’s face above its step', () => {
    expect(templateLine(AGENTS)[1]?.agent).toEqual({ id: 'version_checker', display: 'Version checker' })
  })
})
