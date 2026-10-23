import { describe, expect, it } from 'vitest'
import templates from '@contracts/fixtures/builder/templates.json'
import type { TemplateView } from '../../api/types'
import { createBody, draftProblems, editableParams, exampleParams, fieldWords, fixedParams, hasProblems, planBlocks } from './plan'

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

describe('the plan shown for a template', () => {
  it('lists every block in order, none of them reached, each with its description', () => {
    const blocks = planBlocks(releaseCheck)
    expect(blocks.map((block) => block.name)).toEqual(['Read GitHub releases', 'Approval gate', 'Create Jira ticket'])
    expect(blocks.every((block) => block.state.kind === 'not_reached')).toBe(true)
    expect(blocks[1]?.description).toBe('An Approver reviews the ticket in Teams.')
  })

  it('prefills each detail with its example', () => {
    expect(exampleParams(releaseCheck)).toEqual({
      repo: 'langchain-ai/langgraph',
      tag_pattern: '^\\d+\\.\\d+\\.\\d+$',
      ticket_project: 'MOCK',
    })
  })
})

describe('which details the Operator fills in', () => {
  it('offers the repository and the Jira project, and keeps the release tag pattern out of the form', () => {
    expect(editableParams(releaseCheck).map((param) => param.name)).toEqual(['repo', 'ticket_project'])
    expect(fixedParams(releaseCheck).map((param) => param.name)).toEqual(['tag_pattern'])
  })
})

describe('the words around one field', () => {
  const served = Object.fromEntries((templates.templates[0]?.params ?? []).map((param) => [param.name, fieldWords(param.description)]))

  it('uses a short description as the label alone', () => {
    expect(served['repo']).toEqual({ label: 'GitHub repository, owner/name', help: null })
    expect(served['ticket_project']).toEqual({ label: 'Jira project key', help: null })
  })

  it('moves everything after the first sentence under the field as help', () => {
    expect(served['last_seen_tag']).toEqual({
      label: 'The last release tag already handled, for example 1.2.14',
      help: 'Leave empty to start from the newest release.',
    })
  })

  it('keeps every later sentence in the help and does not split inside a version number', () => {
    expect(fieldWords('Release 1.2.3 is the start. Leave empty for the newest. Ask the team if unsure.')).toEqual({
      label: 'Release 1.2.3 is the start',
      help: 'Leave empty for the newest. Ask the team if unsure.',
    })
  })
})

describe('checking the details before saving', () => {
  const filled = { name: 'LangGraph releases', params: exampleParams(releaseCheck) }

  it('accepts the prefilled examples', () => {
    expect(hasProblems(draftProblems(releaseCheck, filled))).toBe(false)
  })

  it('names the field that is empty, next to its own name in the template', () => {
    const problems = draftProblems(releaseCheck, { name: '  ', params: { repo: '', tag_pattern: '', ticket_project: 'MOCK' } })
    expect(problems.name).toBe('Give the use case a name.')
    expect(Object.keys(problems.params)).toEqual(['repo'])
    expect(hasProblems(problems)).toBe(true)
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
