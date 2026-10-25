import { describe, expect, it } from 'vitest'
import type { TemplateView } from '../../api/types'
import { createBody, exampleParams } from './plan'

const releaseCheck: TemplateView = {
  key: 'release_check',
  name: 'Release check',
  description: 'Watch a public GitHub repository and open a ticket when new releases appear.',
  blocks: [
    { key: 'read_releases', name: 'Read GitHub releases', description: 'The Release checker reads the releases.', kind: 'agent' },
    { key: 'approval_gate', name: 'Approval gate', description: 'An Approver reviews the ticket in Teams.', kind: 'approval' },
    { key: 'create_ticket', name: 'Create Jira ticket', description: 'One ticket in the chosen project.', kind: 'write_action' },
  ],
  params: [
    { name: 'repo', description: 'GitHub repository, owner/name', example: 'langchain-ai/langgraph' },
    { name: 'tag_pattern', description: 'Regular expression a release tag must match', example: '^\\d+\\.\\d+\\.\\d+$' },
    { name: 'ticket_project', description: 'Jira project key', example: 'MOCK' },
  ],
}

describe('the first run on the overview', () => {
  it('prefills each detail with its example', () => {
    expect(exampleParams(releaseCheck)).toEqual({
      repo: 'langchain-ai/langgraph',
      tag_pattern: '^\\d+\\.\\d+\\.\\d+$',
      ticket_project: 'MOCK',
    })
  })
})

describe('what is sent when the use case is saved', () => {
  it('sends the template key, the trimmed name and task, and every detail by its name', () => {
    expect(createBody(releaseCheck, '  Check for new releases.  ', { name: ' LangGraph releases ', params: { repo: ' a/b ', tag_pattern: ' ^x$ ', ticket_project: 'MOCK' } })).toEqual({
      template: 'release_check',
      name: 'LangGraph releases',
      instruction: 'Check for new releases.',
      params: { repo: 'a/b', tag_pattern: '^x$', ticket_project: 'MOCK' },
    })
  })
})
