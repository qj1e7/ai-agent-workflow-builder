import { describe, expect, it } from 'vitest'
import { PLATFORM_AGENTS } from './agents'

const OLD_NAMES = ['Flint', 'Forge', 'Striker', 'Spark Map', 'Scout', 'Analyst', 'Messenger', 'Clerk', 'Fixer', 'Kindling', 'Firebreak', 'Ember']

describe('the agents that fix a stopped run', () => {
  it('lists the AI troubleshooter, the Fix drafter and the Scenario writer after the Planner', () => {
    expect(PLATFORM_AGENTS.map((agent) => agent.id)).toEqual(['planner', 'troubleshooter', 'fix_drafter', 'scenario_writer'])
  })

  it('says the troubleshooter still only explains, and what Fix it for me does', () => {
    const troubleshooter = PLATFORM_AGENTS.find((agent) => agent.id === 'troubleshooter')
    expect(troubleshooter?.rules).toEqual(['Only explains. It never changes a run', 'Fix it for me drafts a change. Nothing changes until an Approver says yes.'])
  })

  it('says each new agent never writes to a real system', () => {
    for (const id of ['fix_drafter', 'scenario_writer']) {
      const agent = PLATFORM_AGENTS.find((one) => one.id === id)
      expect(agent?.rules.join(' ')).toContain('never')
      expect(agent?.reach).toMatch(/practice/i)
    }
  })

  it('uses none of the old themed names', () => {
    const words = JSON.stringify(PLATFORM_AGENTS)
    for (const name of OLD_NAMES) expect(words).not.toContain(name)
  })
})
