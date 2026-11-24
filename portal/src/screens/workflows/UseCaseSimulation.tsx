import { useUseCaseSimulateAgain, useUseCaseSimulation } from '../../api/workflowQueries'
import { SimulationResult } from '../drafted/SimulationResult'

/**
 * The Check of a workflow the Planner built from our blocks: its current version tried on practice systems, as a drafted card shows
 * its revision (ADR 0054). It shows nothing before the platform answers, and nothing when the version has nothing to try. Try
 * again names the version it read, so a newer version is never tried by it.
 */
export function UseCaseSimulation({ useCaseId }: { useCaseId: string }) {
  const tried = useUseCaseSimulation(useCaseId).data
  const again = useUseCaseSimulateAgain(useCaseId)
  if (!tried?.simulation) return null
  return <SimulationResult simulation={tried.simulation} tryAgain={{ pending: again.isPending, press: (outcome) => again.mutate(tried.version, outcome) }} />
}
