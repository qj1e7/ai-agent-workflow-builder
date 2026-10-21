import { describe, expect, it } from 'vitest'
import { splitActionLine } from './describe'

describe('splitActionLine', () => {
  it("splits the proposal's line into the action and the title at the first colon, and keeps a line without one whole", () => {
    expect(splitActionLine('Create Jira ticket in MOCK: New LangGraph releases: 1.2.16, 1.2.15')).toEqual({
      action: 'Create Jira ticket in MOCK',
      title: 'New LangGraph releases: 1.2.16, 1.2.15',
    })
    expect(splitActionLine('Create a ticket')).toEqual({ action: null, title: 'Create a ticket' })
    expect(splitActionLine(': untitled')).toEqual({ action: null, title: ': untitled' })
    expect(splitActionLine('Create a ticket: ')).toEqual({ action: null, title: 'Create a ticket: ' })
  })
})
