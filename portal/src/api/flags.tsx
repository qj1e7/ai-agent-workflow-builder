import { createContext, useContext, type ReactNode } from 'react'
import type { PortalConfig } from './config'

const NewWorkflowSteps = createContext(false)

/** Tells the routes and Home whether the old New workflow is on, from /config.json. */
export function FlagsProvider({ config, children }: { config: Pick<PortalConfig, 'newWorkflowSteps'>; children: ReactNode }) {
  return <NewWorkflowSteps.Provider value={config.newWorkflowSteps}>{children}</NewWorkflowSteps.Provider>
}

export function useNewWorkflowSteps(): boolean {
  return useContext(NewWorkflowSteps)
}
