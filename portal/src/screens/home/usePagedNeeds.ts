import { useMemo } from 'react'
import { useNeedsPages, type Pager } from '../../api/homeQueries'
import type { HomeOut } from '../../api/types'
import { needsOf, type Needs } from './home'

/** Needs you with every page Show more has read, from the same pages as its count. */
export function usePagedNeeds(home: HomeOut | undefined): { readonly needs: Needs | null; readonly pager: Pager } {
  const { home: paged, ...pager } = useNeedsPages(home)
  const needs = useMemo(() => (paged ? needsOf(paged) : null), [paged])
  return { needs, pager }
}
