import { InfiniteQueryObserver, QueryClient, type InfiniteData } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { readMore } from './homeQueries'

interface Page {
  readonly rows: readonly string[]
  readonly total: number
  readonly next: string | null
}

const PAGE = 10
const KEY = ['home', 'alice', 'test-list'] as const

/** A platform list read newest first, a page at a time after the last row sent, as the paged routes read it. */
function platform(count: number) {
  const rows = Array.from({ length: count }, (_, n) => `row_${String(count - n).padStart(3, '0')}`)
  const asked: (string | null)[] = []
  return {
    rows,
    asked,
    fail: false,
    read(after: string | null): Promise<Page> {
      asked.push(after)
      if (this.fail) return Promise.reject(new Error('down'))
      const start = after === null ? 0 : rows.indexOf(after) + 1
      const page = rows.slice(start, start + PAGE)
      return Promise.resolve({ rows: page, total: rows.length, next: start + PAGE < rows.length ? (page.at(-1) ?? null) : null })
    },
  }
}

async function opened(list: ReturnType<typeof platform>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const observer = new InfiniteQueryObserver<Page, Error, InfiniteData<Page, string | null>, typeof KEY, string | null>(client, {
    queryKey: KEY,
    queryFn: ({ pageParam }) => list.read(pageParam),
    initialPageParam: null,
    getNextPageParam: (last) => last.next,
  })
  const first = await list.read(null)
  list.asked.length = 0
  client.setQueryData<InfiniteData<Page, string | null>>(KEY, { pages: [first], pageParams: [null] })
  return { client, observer, first }
}

const counts = (page: Page) => String(page.total)
const drawn = (client: QueryClient) => client.getQueryData<InfiniteData<Page, string | null>>(KEY)?.pages.flatMap((page) => page.rows) ?? []
const totals = (client: QueryClient) => client.getQueryData<InfiniteData<Page, string | null>>(KEY)?.pages.map((page) => page.total) ?? []

describe('Show more reads the next page', () => {
  it('adds the next page after the first when nothing changed between the reads', async () => {
    const list = platform(15)
    const { client, observer, first } = await opened(list)

    const failed = await readMore([first], observer, counts)

    expect(failed).toBe(false)
    expect(list.asked).toEqual(['row_006'])
    expect(drawn(client)).toEqual(list.rows)
  })

  it('reads every page again from the first when the count changed between reads, so the rows and the count come from one read', async () => {
    const list = platform(15)
    const { client, observer, first } = await opened(list)
    list.rows.unshift('row_new')

    await readMore([first], observer, counts)

    expect(list.asked, 'the next page, then every page again from the first').toEqual(['row_006', null, 'row_007'])
    expect(drawn(client)).toEqual(list.rows)
    expect(totals(client)).toEqual([16, 16])
  })

  it('reads every page again when the count says more but no page is left to read', async () => {
    const list = platform(15)
    const { client, observer } = await opened(list)
    const stale: Page = { rows: list.rows.slice(0, PAGE), total: 15, next: null }

    await readMore([stale], observer, counts)

    expect(list.asked).toEqual([null, 'row_006'])
    expect(drawn(client)).toEqual(list.rows)
  })

  it('says so when the read fails', async () => {
    const list = platform(15)
    const { observer, first } = await opened(list)
    list.fail = true

    expect(await readMore([first], observer, counts)).toBe(true)
  })
})
