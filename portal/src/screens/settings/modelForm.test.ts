import { describe, expect, it } from 'vitest'
import connected from '@contracts/fixtures/settings/connect.connected.json'
import active from '@contracts/fixtures/settings/model.active.json'
import empty from '@contracts/fixtures/settings/model.empty.json'
import type { Connected, ModelSettingsView } from '../../api/types'
import {
  OTHER,
  addressFor,
  answerTime,
  connectBody,
  hostOf,
  maskedKey,
  missingForConnect,
  saveBody,
  savedKeyFits,
  startingChoice,
  suggestedModel,
} from './modelForm'

const view = active as ModelSettingsView
const found = connected as Connected

describe('hostOf', () => {
  it('reads the host in lower case', () => {
    expect(hostOf('https://LLM-Gateway.aisg.sg/v1')).toBe('llm-gateway.aisg.sg')
  })

  it('gives nothing for text that is not an address', () => {
    expect(hostOf('llm-gateway.aisg.sg')).toBe('')
    expect(hostOf('')).toBe('')
  })
})

describe('addressFor', () => {
  it('uses the known provider address, or what was typed for another address', () => {
    expect(addressFor('aisg', view.providers, 'ignored')).toBe('https://llm-gateway.aisg.sg')
    expect(addressFor(OTHER, view.providers, '  https://ai.ncs.example/v1 ')).toBe('https://ai.ncs.example/v1')
  })
})

describe('savedKeyFits', () => {
  it('lets the saved key stand in only at the host it was saved for', () => {
    expect(savedKeyFits(view.active, 'https://llm-gateway.aisg.sg')).toBe(true)
    expect(savedKeyFits(view.active, 'https://api.openai.com/v1')).toBe(false)
    expect(savedKeyFits(view.active, 'not an address')).toBe(false)
    expect(savedKeyFits(null, 'https://llm-gateway.aisg.sg')).toBe(false)
  })
})

describe('suggestedModel', () => {
  it('picks the first suggested model, then the first model, then nothing', () => {
    expect(suggestedModel(found.models)).toBe('claude-haiku-5-5')
    expect(suggestedModel([{ id: 'a', display: 'a', suggested: false }])).toBe('a')
    expect(suggestedModel([])).toBe('')
  })
})

describe('maskedKey', () => {
  it('shows only the last two characters', () => {
    expect(maskedKey('x7')).toBe('•••••••••••• x7')
  })
})

describe('connectBody', () => {
  it('names a known provider by id and sends the trimmed key', () => {
    expect(connectBody('aisg', '', ' sk-key ', false)).toEqual({
      provider_id: 'aisg',
      api_key: 'sk-key',
      use_saved_key: false,
    })
  })

  it('sends a typed address, or asks for the saved key instead of a pasted one', () => {
    expect(connectBody(OTHER, ' https://ai.ncs.example ', 'ignored', true)).toEqual({
      base_url: 'https://ai.ncs.example',
      use_saved_key: true,
    })
  })
})

describe('saveBody', () => {
  it('saves the address and style that Connect found, not what was typed', () => {
    expect(saveBody(found, 'claude-haiku-5-5', ' sk-key ', false)).toEqual({
      style: 'anthropic',
      base_url: 'https://llm-gateway.aisg.sg',
      model: 'claude-haiku-5-5',
      api_key: 'sk-key',
      use_saved_key: false,
    })
    expect(saveBody(found, 'claude-sonnet-5-5', '', true)).toMatchObject({ use_saved_key: true })
  })
})

describe('missingForConnect', () => {
  it('asks for an address and a key before Connect can go', () => {
    expect(missingForConnect(OTHER, '  ', 'sk-key', false)).toBe('Type the address first.')
    expect(missingForConnect('aisg', '', ' ', false)).toBe('Paste the key first.')
    expect(missingForConnect('aisg', '', '', true)).toBeNull()
    expect(missingForConnect(OTHER, 'https://x.example', 'sk-key', false)).toBeNull()
  })
})

describe('startingChoice', () => {
  it('starts at the saved model\'s provider, at its address when it is not a known one, or at the first provider', () => {
    expect(startingChoice(view)).toEqual({ choice: 'aisg', typed: '' })
    const elsewhere = { ...view, active: view.active && { ...view.active, base_url: 'https://ai.ncs.example/v1' } }
    expect(startingChoice(elsewhere)).toEqual({ choice: OTHER, typed: 'https://ai.ncs.example/v1' })
    expect(startingChoice(empty as ModelSettingsView)).toEqual({ choice: 'aisg', typed: '' })
  })
})

describe('answerTime', () => {
  it('says under a second when the answer rounds to nothing', () => {
    expect([answerTime(0), answerTime(0.4)]).toEqual(['under a second', 'under a second'])
  })

  it('names the seconds otherwise, with one second singular', () => {
    expect([answerTime(1), answerTime(1.4), answerTime(11.2)]).toEqual(['1 second', '1.4 seconds', '11.2 seconds'])
  })
})
