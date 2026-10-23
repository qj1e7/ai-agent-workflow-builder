import { Route, Routes } from 'react-router'
import { ApprovalPage } from './screens/approval/ApprovalPage'
import { ApprovalsPage } from './screens/approval/ApprovalsPage'
import { BuilderPage } from './screens/builder/BuilderPage'
import { JiraPage } from './screens/jira/JiraPage'
import { NotFoundPage } from './screens/NotFoundPage'
import { OverviewPage } from './screens/overview/OverviewPage'
import { RunPage } from './screens/run/RunPage'
import { SettingsPage } from './screens/settings/SettingsPage'
import { TeamsPage } from './screens/teams/TeamsPage'
import { AppShell } from './ui/AppShell'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="runs/:runId" element={<RunPage />} />
        <Route path="builder" element={<BuilderPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="approvals/:approvalId" element={<ApprovalPage />} />
        <Route path="teams" element={<TeamsPage />} />
        <Route path="jira" element={<JiraPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
