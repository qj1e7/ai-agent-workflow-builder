import { afterEach, describe, expect, it } from 'vitest'
import { newIdempotencyKey } from './idempotency'

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const original = Object.getOwnPropertyDescriptor(crypto, 'randomUUID') ?? Object.getOwnPropertyDescriptor(Object.getPrototypeOf(crypto) as object, 'randomUUID')

afterEach(() => {
  if (original) Object.defineProperty(crypto, 'randomUUID', original)
})

function twoHundredKeys(): Set<string> {
  return new Set(Array.from({ length: 200 }, () => newIdempotencyKey()))
}

describe('newIdempotencyKey', () => {
  it('is a version 4 UUID that differs on every call where randomUUID exists', () => {
    expect(typeof crypto.randomUUID).toBe('function')
    const keys = twoHundredKeys()
    expect(keys.size).toBe(200)
    for (const key of keys) expect(key).toMatch(V4)
  })

  it('still gives a version 4 UUID that differs on every call where randomUUID is missing, as over plain HTTP', () => {
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true, writable: true })
    expect(typeof crypto.randomUUID).toBe('undefined')
    const keys = twoHundredKeys()
    expect(keys.size).toBe(200)
    for (const key of keys) expect(key).toMatch(V4)
  })
})
