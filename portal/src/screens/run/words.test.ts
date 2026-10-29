import { describe, expect, it } from 'vitest'
import { PRODUCT } from '../../shell/product'
import { speakerName } from './words'

describe('the run chat', () => {
  it('names the app by its full name', () => {
    expect(speakerName({ kind: 'app' })).toBe(PRODUCT)
    expect(PRODUCT).toBe('AI Workflow Builder')
  })
})
