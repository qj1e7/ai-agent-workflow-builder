import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { DecidedReply, FollowingUpItem, FollowingUpPage, HomeOut, NeedsPage, WaitingItem, WaitingPage } from './types'

export const HOME_REFRESH_MS = 15_000

export const homeKey = (user: string) => ['home', user] as const

export function useHome({ enabled = true }: { enabled?: boolean } = {}) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: homeKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/home')),
    refetchInterval: HOME_REFRESH_MS,
    enabled,
  })
}

/** What Show more needs from a paged list: whether a read is going, whether the last one failed, and the press. */
export interface Pager {
  readonly busy: boolean
  readonly failed: boolean
  readonly showMore: () => void
}

interface Paged<P> extends Pager {
  /** Every page read so far, from the first, once Show more was pressed. Until then Home's own rows are the first page. */
  readonly pages: readonly P[] | undefined
}

type Paging = { readonly next: string | null }

/** What Show more uses of a paged query. Each read answers with the query as it then stands. */
interface PagesRead<P> {
  readonly data?: { readonly pages: readonly P[] } | undefined
  readonly isError: boolean
}

export interface PagedRead<P> {
  readonly fetchNextPage: () => Promise<PagesRead<P>>
  readonly refetch: () => Promise<PagesRead<P>>
}

const oneCount = <P,>(pages: readonly P[], counts: (page: P) => string): boolean => new Set(pages.map(counts)).size <= 1

/**
 * One press of Show more over `pages`, the pages drawn now. It reads the next page. When that page counts differently from the
 * pages before it, a row came or went between the reads, so every page is read again from the first, and the rows and the count
 * come from one read (principle 7). With no next page while the count says more, the pages are out of date: they are read again,
 * then the page after them. True when a read failed.
 */
export async function readMore<P extends Paging>(pages: readonly P[], query: PagedRead<P>, counts: (page: P) => string): Promise<boolean> {
  if (pages.at(-1)?.next) {
    const read = await query.fetchNextPage()
    if (read.isError) return true
    if (oneCount(read.data?.pages ?? [], counts)) return false
    return (await query.refetch()).isError
  }
  const again = await query.refetch()
  if (again.isError) return true
  return again.data?.pages.at(-1)?.next ? (await query.fetchNextPage()).isError : false
}

/**
 * A list Home answers the first page of, and a paged read goes on with. The first Show more takes Home's page as page one and
 * reads the next. From then on every refresh reads each page again in order, from the first, so a row that arrives while the
 * person reads is never skipped between pages. Under `['home', user]`, so whatever refreshes Home refreshes the pages too.
 * `counts` names a page's totals, which must agree across the pages drawn.
 */
function usePages<P extends Paging>(list: string, first: P | undefined, read: (after: string | null) => Promise<P>, counts: (page: P) => string): Paged<P> {
  const queryClient = useQueryClient()
  const key = [...homeKey(useCacheScope()), list] as const
  const query = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) => read(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next,
    enabled: (cached) => cached.state.data !== undefined,
    refetchInterval: HOME_REFRESH_MS,
  })
  const [reading, setReading] = useState(false)
  const [failed, setFailed] = useState(false)
  function showMore() {
    const pages = query.data?.pages ?? (first ? [first] : null)
    if (pages === null || reading) return
    if (query.data === undefined) queryClient.setQueryData<InfiniteData<P, string | null>>(key, { pages: [...pages], pageParams: [null] })
    setReading(true)
    setFailed(false)
    void readMore(pages, query, counts).then((readFailed) => {
      setReading(false)
      setFailed(readFailed)
    })
  }
  return { pages: query.data?.pages, busy: reading, failed, showMore }
}

const needsOfHome = (home: HomeOut): NeedsPage => ({
  approvals: home.approvals,
  approvals_total: home.approvals_total,
  stopped: home.stopped,
  stopped_total: home.stopped_total,
  declined: home.declined,
  declined_total: home.declined_total,
  questions_for_me: home.questions_for_me,
  questions_for_me_total: home.questions_for_me_total,
  next: home.needs_next,
})

/** Home with the pages of Needs you read so far in place of its first page. Each total is the newest page's, so it agrees with the rows. */
export function withNeedsPages(home: HomeOut, pages: readonly NeedsPage[] | undefined): HomeOut {
  const last = pages?.at(-1)
  if (!pages || !last) return home
  return {
    ...home,
    approvals: pages.flatMap((page) => page.approvals),
    approvals_total: last.approvals_total,
    stopped: pages.flatMap((page) => page.stopped),
    stopped_total: last.stopped_total,
    declined: pages.flatMap((page) => page.declined),
    declined_total: last.declined_total,
    questions_for_me: pages.flatMap((page) => page.questions_for_me),
    questions_for_me_total: last.questions_for_me_total,
    needs_next: last.next,
  }
}

/** Needs you's runs waiting for a yes, stopped runs, declined test runs and questions, as far as Show more has read them. */
export function useNeedsPages(home: HomeOut | undefined): { readonly home: HomeOut | undefined } & Pager {
  const client = useApiClient()
  const paged = usePages(
    'needs',
    home ? needsOfHome(home) : undefined,
    async (after) => unwrap(await client.GET('/api/v1/home/needs', { params: { query: after === null ? {} : { after } } })),
    (page) => [page.approvals_total, page.stopped_total, page.declined_total, page.questions_for_me_total].join(' '),
  )
  const merged = useMemo(() => (home ? withNeedsPages(home, paged.pages) : undefined), [home, paged.pages])
  return { home: merged, busy: paged.busy, failed: paged.failed, showMore: paged.showMore }
}

export interface Rows<T> extends Pager {
  readonly items: readonly T[]
  readonly total: number
}

/** The person's own requests to the team, as far as Show more has read them. */
export function useFollowingPages(home: HomeOut | undefined): Rows<FollowingUpItem> {
  const client = useApiClient()
  const first: FollowingUpPage | undefined = home && { following_up: home.following_up, following_up_total: home.following_up_total, next: home.following_up_next }
  const paged = usePages(
    'following-up',
    first,
    async (after) => unwrap(await client.GET('/api/v1/home/following-up', { params: { query: after === null ? {} : { after } } })),
    (page) => String(page.following_up_total),
  )
  const items = useMemo(() => (paged.pages ? paged.pages.flatMap((page) => page.following_up) : (home?.following_up ?? [])), [paged.pages, home?.following_up])
  const total = paged.pages?.at(-1)?.following_up_total ?? home?.following_up_total ?? 0
  return { items, total, busy: paged.busy, failed: paged.failed, showMore: paged.showMore }
}

/** The person's own runs that wait for someone else's yes, as far as Show more has read them. */
export function useWaitingPages(home: HomeOut | undefined): Rows<WaitingItem> {
  const client = useApiClient()
  const first: WaitingPage | undefined = home && { waiting_on_others: home.waiting_on_others, waiting_on_others_total: home.waiting_on_others_total, next: home.waiting_on_others_next }
  const paged = usePages(
    'waiting-on-others',
    first,
    async (after) => unwrap(await client.GET('/api/v1/home/waiting-on-others', { params: { query: after === null ? {} : { after } } })),
    (page) => String(page.waiting_on_others_total),
  )
  const items = useMemo(() => (paged.pages ? paged.pages.flatMap((page) => page.waiting_on_others) : (home?.waiting_on_others ?? [])), [paged.pages, home?.waiting_on_others])
  const total = paged.pages?.at(-1)?.waiting_on_others_total ?? home?.waiting_on_others_total ?? 0
  return { items, total, busy: paged.busy, failed: paged.failed, showMore: paged.showMore }
}

/** The signed-in person's own decisions, newest first. `verdict` keeps only approvals or only declines. */
export function useDecisions(verdict: DecidedReply['only']) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: ['decisions', user, verdict] as const,
    queryFn: async () => unwrap(await client.GET('/api/v1/decisions', { params: { query: verdict === null ? {} : { verdict } } })),
  })
}
