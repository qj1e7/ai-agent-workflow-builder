import added from '@contracts/fixtures/watchlist/add-software.json'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { checkAdd, refusedAdd, repoFrom, versionFrom, WORDS } from './addForm'

describe('repoFrom', () => {
  it('takes owner/name as typed, or out of a pasted GitHub address', () => {
    expect(repoFrom(' langchain-ai/langgraph ')).toBe('langchain-ai/langgraph')
    expect(repoFrom('https://github.com/langchain-ai/langgraph')).toBe('langchain-ai/langgraph')
    expect(repoFrom('github.com/langchain-ai/langgraph/releases/tag/1.2.16')).toBe('langchain-ai/langgraph')
    expect(repoFrom('https://www.github.com/redis/redis.git')).toBe('redis/redis')
  })

  it('leaves anything else for the check to refuse', () => {
    expect(repoFrom('https://gitlab.com/group/project')).toBe('https://gitlab.com/group/project')
  })
})

describe('versionFrom', () => {
  it('drops the v that release tags carry', () => {
    expect(versionFrom('v1.2.14')).toBe('1.2.14')
    expect(versionFrom(' 1.2.14 ')).toBe('1.2.14')
    expect(versionFrom('version')).toBe('version')
  })
})

describe('checkAdd', () => {
  it('builds the body the platform takes, with no version when it is left empty', () => {
    expect(checkAdd({ name: ' LangGraph ', repo: 'langchain-ai/langgraph', ourVersion: 'v1.2.14' })).toEqual({
      ok: true,
      body: added,
    })
    expect(checkAdd({ name: 'Redis', repo: 'https://github.com/redis/redis', ourVersion: '' })).toEqual({
      ok: true,
      body: { name: 'Redis', repo: 'redis/redis', our_version: null },
    })
  })

  it('names every field with a problem at once', () => {
    expect(checkAdd({ name: '', repo: '', ourVersion: '' })).toEqual({
      ok: false,
      problems: { name: WORDS.nameMissing, repo: WORDS.repoMissing },
    })
    expect(checkAdd({ name: 'x'.repeat(81), repo: 'langgraph', ourVersion: '1.2' })).toEqual({
      ok: false,
      problems: { name: WORDS.nameTooLong, repo: WORDS.repoShape, ourVersion: WORDS.version },
    })
  })
})

describe('refusedAdd', () => {
  const body = { name: 'LangGraph', repo: 'langchain-ai/langgraph', our_version: null }

  it('puts a repository that is already watched on the repository field', () => {
    const refused = refusedAdd(new ApiError(409, { detail: 'langchain-ai/langgraph is already watched' }), body)
    expect(refused).toEqual({ fields: { repo: 'langchain-ai/langgraph is already on the list.' }, form: null })
  })

  it('turns the platform field problems into our words, and keeps a problem about the whole list', () => {
    const fields = new ApiError(422, {
      detail: [
        { loc: ['body', 'repo'], msg: "String should match pattern '^...$'", type: 'string_pattern_mismatch' },
        { loc: ['body', 'our_version'], msg: "String should match pattern '^...$'", type: 'string_pattern_mismatch' },
      ],
    })
    expect(refusedAdd(fields, body)).toEqual({
      fields: { repo: WORDS.repoShape, ourVersion: WORDS.version },
      form: null,
    })
    const full = new ApiError(422, { detail: [{ loc: ['body'], msg: 'The watchlist holds 100 software at most' }] })
    expect(refusedAdd(full, body)).toEqual({ fields: {}, form: 'The watchlist holds 100 software at most.' })
  })

  it('leaves other errors to the usual explanation', () => {
    expect(refusedAdd(new ApiError(403, { detail: 'Only an Operator can do this' }), body)).toBeNull()
    expect(refusedAdd(new TypeError('offline'), body)).toBeNull()
    expect(refusedAdd(new ApiError(422, { detail: [{ loc: ['query', 'toString'] }] }), body)).toBeNull()
  })
})
