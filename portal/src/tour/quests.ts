import type { TourStop } from './stops'

/** What finishes a step. Each one waits for something the person really does in the app. */
export type StepDone =
  | { readonly kind: 'read' }
  | { readonly kind: 'press'; readonly stop: TourStop }
  | { readonly kind: 'see'; readonly stop: TourStop }
  | { readonly kind: 'page'; readonly at: string }
  | { readonly kind: 'user'; readonly id: string }
  | { readonly kind: 'role'; readonly role: 'operator' | 'approver' }

export interface TourStep {
  readonly id: string
  /** A few words for the quest's checklist. */
  readonly label: string
  /** What to do now. */
  readonly say: string
  /** What happens, or why it matters. */
  readonly why?: string
  readonly glow?: TourStop
  /** Another part of the page the card should not cover, such as a message the step asks the person to watch. */
  readonly keepClear?: TourStop
  readonly done: StepDone
  /** The page this step happens on, so the card can send the person back to it. */
  readonly where?: Where
  /** With real sign-in there is no user menu, so a step that switches users only explains. */
  readonly signedIn?: string
  /** What to do when the person is on the right page but the stop is not there, because an earlier step was undone. */
  readonly lost?: string
}

export interface Where {
  readonly at: string
  /** Finishes the sentence "This step is on ...". */
  readonly page: string
  /** Where the link leads, when the page itself has no fixed address, and what the link says. */
  readonly to?: string
  readonly go?: string
}

export interface Quest {
  readonly id: string
  readonly title: string
  readonly steps: readonly TourStep[]
}

const BUILDER: Where = { at: '/builder', page: 'the Builder page' }
const SOFTWARE: Where = { at: '/software', page: 'the Software page' }
const A_RUN: Where = { at: '/runs/*', page: "a run's page", to: '/', go: 'Open Runs' }
const AN_APPROVAL: Where = { at: '/approvals/*', page: 'an approval page', to: '/approvals', go: 'Open Approvals' }

export const QUESTS: readonly Quest[] = [
  {
    id: 'around',
    title: 'Find your way around',
    steps: [
      {
        id: 'welcome',
        label: 'Start the tour',
        say: 'This tour runs on the real app. Each step waits until you do it, then ticks itself off.',
        why: 'Runs and tickets you make here are real in this Portal. The Teams and Jira pages are practice copies, so nothing reaches the real ones.',
        done: { kind: 'read' },
      },
      {
        id: 'open-users',
        label: 'Open the user menu',
        say: 'Press your name at the top right.',
        why: 'On this test setup you can act as three people, to see what each role can do.',
        glow: 'user-menu',
        done: { kind: 'press', stop: 'user-menu' },
        signedIn: 'Your name and role are at the top right. You are signed in with your own account.',
      },
      {
        id: 'be-alice',
        label: 'Act as Alice',
        say: 'Pick Alice.',
        why: 'Alice is an Operator and an Approver. Bob only approves. Carol only runs tasks. Operators describe and run tasks. Approvers say yes or no before anything is written.',
        glow: 'user-menu',
        done: { kind: 'user', id: 'alice' },
        signedIn: 'Operators describe and run tasks. Approvers say yes or no before anything is written.',
      },
      {
        id: 'theme',
        label: 'Try the theme',
        say: 'Press the moon or the sun to switch between light and dark.',
        why: 'Press it again any time to switch back.',
        glow: 'theme',
        done: { kind: 'press', stop: 'theme' },
      },
    ],
  },
  {
    id: 'model',
    title: 'Connect an AI model',
    steps: [
      {
        id: 'open-settings',
        label: 'Open Settings',
        say: 'Press the gear at the top right.',
        glow: 'settings',
        done: { kind: 'page', at: '/settings' },
      },
      {
        id: 'model-on',
        label: 'Connect a model',
        say: 'If a green line names your model, you are connected. If not, pick where your model is, paste its key and press Connect.',
        why: 'The Room lead and the agents use this model to plan and to work. Every change here is recorded with who made it.',
        glow: 'model-on',
        done: { kind: 'see', stop: 'model-on' },
        where: { at: '/settings', page: 'the Settings page' },
      },
    ],
  },
  {
    id: 'plan',
    title: 'Plan a task',
    steps: [
      {
        id: 'open-builder',
        label: 'Open the Builder',
        say: 'Open the Builder from the menu.',
        why: 'Here you describe a task in plain English, and the Room lead plans who does it.',
        glow: 'nav-builder',
        done: { kind: 'page', at: '/builder' },
      },
      {
        id: 'plan-example',
        label: 'Plan the example',
        say: 'Press Plan the example.',
        why: 'The Room lead reads the task and picks saved agents for it. This takes a few seconds. You can also type your own task and press Plan it.',
        glow: 'plan-example',
        done: { kind: 'see', stop: 'plan-result' },
        where: BUILDER,
      },
      {
        id: 'read-plan',
        label: 'Read the plan',
        say: "Read the Room lead's plan: which agent it picked, why, and what it still needs from you.",
        why: 'When no saved agent fits, it drafts a new one for you to check. When no tool can do the task, it says so.',
        glow: 'plan',
        done: { kind: 'read' },
        where: BUILDER,
        lost: 'No plan on screen? Press Plan the example again.',
      },
      {
        id: 'fill-details',
        label: 'Fill in the details',
        say: 'Check the details under the agent. If Jira project is empty, type MOCK.',
        why: 'MOCK is the practice Jira project. Each run uses these details, and the agent may only touch the project you give it.',
        glow: 'run-details',
        done: { kind: 'read' },
        where: BUILDER,
        lost: 'No plan on screen? Press Plan the example again.',
      },
      {
        id: 'save-run',
        label: 'Save and run',
        say: 'Press Save and run.',
        why: 'This saves the task as a use case and starts a run. You will land on the run page.',
        glow: 'save-and-run',
        done: { kind: 'page', at: '/runs/*' },
        where: BUILDER,
        lost: 'No plan on screen? Press Plan the example again.',
      },
    ],
  },
  {
    id: 'watch',
    title: 'Watch the run',
    steps: [
      {
        id: 'run-line',
        label: 'Follow the line',
        say: 'This line is the live activity view. It shows where the work is, from Started to Done.',
        why: 'The Room lead brings in agents. They read what they need, then propose a ticket. The run stops at the approval gate until a person decides.',
        glow: 'run-line',
        done: { kind: 'read' },
        where: A_RUN,
      },
      {
        id: 'speed',
        label: 'Change the speed',
        say: 'Press 2x or Instant.',
        why: 'A finished run replays from the start. Instant jumps to the newest state.',
        glow: 'speed',
        done: { kind: 'press', stop: 'speed' },
        where: A_RUN,
      },
      {
        id: 'minutes',
        label: 'Open the Minutes',
        say: 'Scroll down to Minutes and press Technical details.',
        why: 'Minutes are the written record of the run: who did what, and when. Technical details add the event names.',
        glow: 'tech-details',
        done: { kind: 'press', stop: 'tech-details' },
        where: A_RUN,
      },
      {
        id: 'gate',
        label: 'Reach the gate',
        say: 'Look at the line above. Is the run waiting for an Approver?',
        why: 'If it ended with nothing to write, there was no new release to report. Run the Release checker from the Agent library on another repository, such as pallets/flask, then come back.',
        glow: 'run-status',
        done: { kind: 'read' },
        where: A_RUN,
      },
    ],
  },
  {
    id: 'approve',
    title: 'Approve as someone else',
    steps: [
      {
        id: 'open-approvals',
        label: 'Open Approvals',
        say: 'Open Approvals from the menu.',
        why: 'It lists every run waiting for an Approver.',
        glow: 'nav-approvals',
        done: { kind: 'page', at: '/approvals' },
      },
      {
        id: 'open-approval',
        label: 'Open the request',
        say: 'Press Open the approval page on your run.',
        glow: 'open-approval',
        done: { kind: 'page', at: '/approvals/*' },
        where: { at: '/approvals', page: 'the Approvals page' },
        lost: 'Nothing waiting? Every run has been decided. Press Skip, or run the Release checker again.',
      },
      {
        id: 'own-work',
        label: 'See the lock',
        say: 'You started this run, so you cannot approve it. Nobody approves their own work.',
        why: 'Copy link sends this page to another Approver. The ticket on this page is exactly what will be written, and nothing else.',
        glow: 'decision',
        done: { kind: 'read' },
        where: AN_APPROVAL,
      },
      {
        id: 'be-bob',
        label: 'Act as Bob',
        say: 'Switch to Bob from the menu at the top right.',
        why: 'Bob is an Approver, and he did not start this run.',
        glow: 'user-menu',
        done: { kind: 'user', id: 'bob' },
        signedIn: 'Ask a teammate who is an Approver, and who did not start this run, to open this page.',
      },
      {
        id: 'decide',
        label: 'Approve or decline',
        say: 'Read what will be written, then press Approve and write to Jira.',
        why: 'Decline stops the run and writes nothing. The short code under the buttons proves the ticket did not change after you read it.',
        glow: 'decide',
        done: { kind: 'press', stop: 'decide' },
        where: AN_APPROVAL,
        lost: 'No buttons? This run has been decided already, or you started it. Press Skip.',
      },
    ],
  },
  {
    id: 'result',
    title: 'See the result',
    steps: [
      {
        id: 'watch-run',
        label: 'Watch the run',
        say: 'Press Watch the run.',
        glow: 'watch-run',
        done: { kind: 'page', at: '/runs/*' },
        where: AN_APPROVAL,
      },
      {
        id: 'written',
        label: 'See the ticket',
        say: 'Wait for the ticket key, such as MOCK-5, at the end of the line.',
        why: 'After the approval the run goes on and writes the ticket. If you declined, nothing is written, so press Skip.',
        glow: 'written',
        done: { kind: 'see', stop: 'written' },
        where: A_RUN,
      },
      {
        id: 'open-jira',
        label: 'Open Jira',
        say: 'Open Jira from the menu.',
        why: 'This practice project shows every ticket that was written, with a link back to its run.',
        glow: 'nav-jira',
        done: { kind: 'page', at: '/jira' },
      },
      {
        id: 'open-teams',
        label: 'Open Teams',
        say: 'Open Teams from the menu.',
        why: 'In real use, approval requests arrive in a Teams channel like this one. Each message links to its approval page and its run.',
        glow: 'nav-teams',
        done: { kind: 'page', at: '/teams' },
      },
    ],
  },
  {
    id: 'build',
    title: 'Build your own agent',
    steps: [
      {
        id: 'be-operator',
        label: 'Act as an Operator',
        say: 'Switch back to Alice from the menu at the top right.',
        why: 'Only Operators build and run agents.',
        glow: 'user-menu',
        done: { kind: 'role', role: 'operator' },
        signedIn: 'Only Operators build and run agents. If you are only an Approver, ask an Operator to show you this part.',
      },
      {
        id: 'open-builder-again',
        label: 'Open the Builder',
        say: 'Open the Builder from the menu.',
        glow: 'nav-builder',
        done: { kind: 'page', at: '/builder' },
      },
      {
        id: 'copy-edit',
        label: 'Copy the starter',
        say: 'In the Agent library, press Copy and edit on the Release checker.',
        why: 'Starter agents cannot be changed, so you work on a copy.',
        glow: 'copy-edit',
        done: { kind: 'see', stop: 'card-editor' },
        where: BUILDER,
      },
      {
        id: 'read-card',
        label: 'Read the agent',
        say: 'An agent has a name, what it does, its steps, and the details to fill in for each run.',
        why: 'Each step uses one tool from a fixed list we built. The platform sets the approvals, not the agent. When no saved agent fits a task, the Room lead drafts one like this for you.',
        glow: 'card-editor',
        done: { kind: 'read' },
        where: BUILDER,
        lost: 'No agent open? Press Copy and edit on the Release checker again.',
      },
      {
        id: 'break-it',
        label: 'Remove a detail',
        say: 'Press Remove under the Jira project detail.',
        why: 'The check under the agent updates as you edit, and says what is missing in plain words.',
        glow: 'remove-jira-detail',
        done: { kind: 'see', stop: 'card-problems' },
        where: BUILDER,
        lost: 'No agent open? Press Copy and edit on the Release checker again.',
      },
      {
        id: 'fix-it',
        label: 'Fix it again',
        say: 'Press Add detail. Name it Jira project, set its kind to Jira project, and give the example MOCK.',
        why: 'When the check says Ready to save, the agent is valid.',
        glow: 'add-detail',
        keepClear: 'card-problems',
        done: { kind: 'see', stop: 'card-ready' },
        where: BUILDER,
        lost: 'No agent open? Press Copy and edit on the Release checker again.',
      },
      {
        id: 'save-agent',
        label: 'Save the agent',
        say: 'Give it a new name if you like, then press Save agent.',
        why: 'A saved agent joins the Agent library. The Room lead can then pick it for later tasks.',
        glow: 'save-agent',
        done: { kind: 'see', stop: 'run-details' },
        where: BUILDER,
        lost: 'No agent open? Press Copy and edit on the Release checker again.',
      },
      {
        id: 'run-agent',
        label: 'Run your agent',
        say: 'Fill in the details and press Save and run to try your agent.',
        why: 'This run goes through the same approval gate as every other.',
        glow: 'save-and-run',
        done: { kind: 'page', at: '/runs/*' },
        where: BUILDER,
        lost: 'No run form? Press Run on your agent in the Agent library.',
      },
    ],
  },
  {
    id: 'software',
    title: 'Watch your software',
    steps: [
      {
        id: 'open-software',
        label: 'Open Software',
        say: 'Open Software from the menu.',
        why: 'It lists the software your team watches. What needs a person comes first.',
        glow: 'nav-software',
        done: { kind: 'page', at: '/software' },
      },
      {
        id: 'schedule',
        label: 'See the schedule',
        say: 'Checks run on a schedule. Change sets the day and the time.',
        why: "A scheduled check counts as the schedule owner's work, so another Approver approves it.",
        glow: 'schedule',
        done: { kind: 'read' },
        where: SOFTWARE,
      },
      {
        id: 'add-software',
        label: 'Add software',
        say: 'Add one. For example, name FastAPI and repository fastapi/fastapi. Then press Add.',
        why: 'Leave Our version empty, and the first check takes the newest version.',
        glow: 'add-form',
        done: { kind: 'press', stop: 'add-software' },
        where: SOFTWARE,
      },
      {
        id: 'check-now',
        label: 'Check now',
        say: 'Press Check now.',
        why: 'One check looks at everything on the list and asks for one approval for all the tickets it proposes.',
        glow: 'check-now',
        done: { kind: 'page', at: '/runs/*' },
        where: SOFTWARE,
      },
    ],
  },
  {
    id: 'trouble',
    title: 'When something goes wrong',
    steps: [
      {
        id: 'failed',
        label: 'Know a failed run',
        say: 'When a run fails, its line turns red where it stopped. The AI troubleshooter says the likely cause and what to do.',
        why: 'Operators see Retry run. Fix the cause first, then retry.',
        done: { kind: 'read' },
      },
      {
        id: 'declined',
        label: 'Know a declined run',
        say: 'A declined run ends with nothing written. The Minutes record who declined it, and when.',
        done: { kind: 'read' },
      },
      {
        id: 'runs',
        label: 'Find any run',
        say: 'Open Runs from the menu.',
        why: 'Runs shows the newest run on its line. Earlier runs are listed under it, and each opens its own page.',
        glow: 'nav-runs',
        done: { kind: 'page', at: '/' },
      },
    ],
  },
]
