import { Backend } from './stack'
import { test as base, expect } from '../../support/test'

export const test = base.extend<object, { backend: Backend }>({
  backend: [
    // Playwright reads the first argument as a destructuring pattern, so it cannot be `_`.
    // eslint-disable-next-line no-empty-pattern
    async ({}, use, workerInfo) => {
      const backend = await Backend.connect(String(workerInfo.project.use.baseURL))
      await use(backend)
      await backend.dispose()
    },
    { scope: 'worker' },
  ],
})

export { expect }
