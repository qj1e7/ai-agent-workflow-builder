import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { agentId, type AgentStatus, type Figure } from '../run'
import { Cast } from './TrackLine'

/** The path each badge icon draws, from src/ui/icons.tsx. */
const MARK: Readonly<Record<Exclude<AgentStatus, 'present'>, string>> = {
  stopped: 'M6.5 6.5l11 11M17.5 6.5l-11 11',
  done: 'M5 12.5l4.5 4.5L19 7.5',
  working: 'M12 4a8 8 0 1 1-8 8',
}

function agent(id: string, name: string, status: AgentStatus): Figure {
  return { key: `agent:${id}`, is: 'agent', id: agentId(id), name, acting: false, status }
}

/** Each figure's markup, from its data-figure to the next one. */
function figuresIn(figures: readonly Figure[]): string[] {
  return renderToStaticMarkup(createElement(Cast, { figures, users: undefined })).split('data-figure=').slice(1)
}

describe('the cast on a stop', () => {
  it('marks each agent on a crowded stop as working, done or stopped, by its icon and not by colour alone', () => {
    const [working, done, stopped] = figuresIn([agent('entra_reader', 'Entra reader', 'working'), agent('admin_reader', 'Admin reader', 'done'), agent('gitlab_reader', 'GitLab reader', 'stopped')])
    expect(working, 'the working reader').toContain(MARK.working)
    expect(done, 'the reader that is done').toContain(MARK.done)
    expect(stopped, 'the reader that stopped').toContain(MARK.stopped)
    expect(stopped, 'the words say it too').toContain('GitLab reader, stopped')
  })

  it("draws the release check's two figures as the template does, with no marks", () => {
    for (const figure of figuresIn([agent('room_lead', 'Room lead', 'present'), agent('release_checker', 'Release checker', 'working')])) {
      for (const mark of Object.values(MARK)) expect(figure).not.toContain(mark)
    }
  })
})
