import { describe, expect, it } from 'vitest'
import type { ToolView } from '../../api/types'
import { accessLabel, approvalWords, cardAccess, faceId, isPlatformAgent, kindLabel, PLATFORM_AGENTS, platformAgentMark, systemOf, toolCountWords, toolKinds, toolsUnavailableWords, versionWords } from './agents'

const TOOLS: ToolView[] = [
  { id: 'jira.search', kind: 'read', name: 'Search Jira', description: '', target_input: null, min_approvers: null },
  { id: 'jira.create_ticket', kind: 'write', name: 'Create a Jira ticket', description: '', target_input: 'jira_project', min_approvers: 1 },
]

describe('read and write labels', () => {
  it('says a read only reads and a write changes data', () => {
    expect(kindLabel('read')).toBe('Reads only')
    expect(kindLabel('write')).toBe('Changes data')
  })

  it('says a write waits for a yes, and from how many Approvers', () => {
    expect(approvalWords(1)).toBe('Waits for a yes from 1 Approver')
    expect(approvalWords(2)).toBe('Waits for a yes from 2 Approvers, one after the other')
    expect(approvalWords(null)).toBe('Waits for a yes')
  })

  it('labels a card by the strongest thing its tools can do', () => {
    const kinds = toolKinds(TOOLS)
    expect(cardAccess({ tools: [], approvals: [] }, kinds)).toBe('none')
    expect(cardAccess({ tools: ['jira.search'], approvals: [] }, kinds)).toBe('reads')
    expect(cardAccess({ tools: ['jira.search', 'jira.create_ticket'], approvals: [] }, kinds)).toBe('writes')
    expect(accessLabel('writes')).toBe('Changes data after a yes')
    expect(accessLabel('none')).toBe('No access to other systems')
  })

  it('still marks a write when the tool list is down, because the card carries its approvals', () => {
    expect(cardAccess({ tools: ['jira.create_ticket'], approvals: [{ tool: 'jira.create_ticket', approvers: 1 }] }, toolKinds(undefined))).toBe('writes')
  })

  it('counts tools', () => {
    expect(toolCountWords(1)).toBe('1 tool')
    expect(toolCountWords(3)).toBe('3 tools')
  })
})

describe('platform agents', () => {
  it('lists the Planner and the AI troubleshooter, and marks only them', () => {
    expect(PLATFORM_AGENTS.map((agent) => agent.id)).toEqual(['planner', 'troubleshooter'])
    expect(platformAgentMark('planner')).toBe('Platform agent')
    expect(platformAgentMark('troubleshooter')).toBe('Platform agent')
    expect(platformAgentMark('version_checker')).toBeNull()
    expect(isPlatformAgent('crd_version_checker')).toBe(false)
  })

})

describe('tools', () => {
  it('names the system each tool reaches', () => {
    expect(systemOf('jira.create_ticket')).toBe('Jira')
    expect(systemOf('github.read_releases')).toBe('GitHub')
  })
})

describe('when the tool list is down', () => {
  it('points at the agent cards only when they show below', () => {
    expect(toolsUnavailableWords(true)).toBe('The tool list is not available right now. The agent cards below are still here.')
    expect(toolsUnavailableWords(false)).toBe('The tool list is not available right now.')
  })
})

describe('cards', () => {
  it('keys a starter card’s face on its id without the crd_ prefix', () => {
    expect(faceId({ card_id: 'crd_version_checker' })).toBe('version_checker')
    expect(faceId({ card_id: 'crd_01JD0WEEKLYSUMMARY000001' })).toBe('01JD0WEEKLYSUMMARY000001')
  })

  it('says where a starter card comes from', () => {
    expect(versionWords({ starter: true, version: 1 })).toBe('Version 1. Ships with the platform')
    expect(versionWords({ starter: false, version: 2 })).toBe('Version 2')
  })
})
