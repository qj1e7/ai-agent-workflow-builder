import { useQuery } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'

export const HOME_REFRESH_MS = 15_000

export const homeKey = (user: string) => ['home', user] as const

export function useHome() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: homeKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/home')),
    refetchInterval: HOME_REFRESH_MS,
  })
}
