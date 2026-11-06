/* Paths for version 3, docs/design/portal-routines/prototype.html.
   A scenario is { id, title, viewport, run(t) }. The ids are stable so version 4 can reuse them.
   Selectors that version 4 may change are all in this file. */

const WEEKLY_STALE = 'Every Friday, list bug tickets with no update for 10 days';
const WEEKLY_SUMMARY = 'every Friday, sum up the tickets we closed this week';
const EMAIL = 'email me a list of open bugs every Monday';

/* Selectors */
const S = {
  ask: '[data-ask]',
  example: (i) => `[data-act="example"][data-arg="${i}"]`,
  time: '#sched-time',
  project: '#fix-project',
  turnOn: '[data-act="turnOn"]',
  testRun: '[data-act="testRun"]',
  review: '[data-act="run"][data-arg="sw"]:has-text("Review and decide")',
  approve: '[data-act="approve"][data-arg="sw"]',
  fixIt: '[data-act="run"][data-arg="issues"]:has-text("See why and fix it")',
  retry: '[data-act="fixIssues"]',
  report: '[data-act="report"]',
  sendReport: '[data-act="sendReport"]',
  doneDialog: '.dialog [data-act="closeModal"]',
  row: (id) => `main [data-act="workflow"][data-arg="${id}"]`,
  teams: '.hdr [data-act="teams"]',
  toast: '.toast',
};

/* The same set-up as a user would do it, without counting it. Used where a task starts after the workflow is on. */
async function turnOnWeekly(k) {
  await k.page.click(S.example(0));
  await k.replied();
  await k.page.fill(S.time, '17:00');
  await k.page.selectOption(S.project, 'MOCK');
  await k.settle();
  await k.page.click(S.turnOn);
  await k.settle(600);
}

const approvedText = /approved, and the platform created the tickets/;

/* Approving ends in a replay of the run. Waiting for its last line is not a user step. */
const approvedOpts = { decision: true, until: approvedText };

const scenarios = [];
const add = (id, title, run, viewports = [1280], extra = {}) => viewports.forEach((viewport) => scenarios.push({ id, title, viewport, run, ...extra }));

/* A. First-time Operator, day one. */
add('A', 'First-time Operator sets up a weekly Jira summary and turns it on', async (t) => {
  await t.setup((k) => k.setDay('one'));
  await t.expectText('Day one Home asks what the team does again and again', /again and again/);
  await t.ask(WEEKLY_SUMMARY, 'every Friday, sum up the tickets we closed this week');
  const left = await t.page.innerText('main');
  const asks = Number((left.match(/(\d+) choices? left/) || [0, 0])[1]);
  t.metric('plannerQuestions', asks);
  await t.expect('The Planner asks back for when it runs and the Jira project', left, /2 choices left: when it runs and the Jira project/);
  await t.field(S.time, '17:00', 'Choose the time', { decision: true });
  await t.select(S.project, 'MOCK', 'Choose the Jira project', { decision: true });
  await t.expectText('Nothing is unclear before turning on', /Nothing is unclear\. One yes turns it on\./);
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Weekly closed ticket summary is on/);
}, [1280, 390]);

/* B. Experienced Operator, a normal week. */
add('B', 'Experienced Operator finds what needs attention and fixes the stopped Morning bug report check', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Needs you lists four things', /Needs you\s+4/);
  await t.expectText('The stopped Morning bug report check is listed with a fix', /Morning bug report check stopped[\s\S]*You can fix this yourself/);
  await t.click(S.fixIt, 'See why and fix it', { nav: true });
  await t.expectText('The AI troubleshooter says what happened', /GitHub says langchain-ai\/langserve doesn’t exist any more/);
  await t.click(S.retry, 'Use langchain-ai/langchain and retry', { decision: true, until: /The workflow now reads langchain-ai\/langchain/ });
  await t.expectText('The retry finished', /Done, nothing new today/);
  await t.setup((k) => k.go('workflows'));
  await t.expectText('Morning bug report check is no longer stopped', /Morning bug report check[\s\S]{0,40}Today: no new bug reports/);
}, [1280, 390]);

/* C. Approver. */
add('C', 'Bob, an Approver only, opens the upgrade request, sees what changes and the evidence, and approves', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.expectText('Bob sees one thing that needs him', /1 thing needs you/);
  await t.click(S.review, 'Review and decide');
  await t.expectText('The page says what will be written', /3 tickets will be created in Jira project MOCK/);
  await t.expectText('The page says nothing else is written', /exactly what will be written, and nothing else/);
  await t.expectText('The evidence is there: the vulnerability record and the active-exploit list', /NVD: CVE-2021-44228[\s\S]*CISA: actively exploited/);
  await t.expectText('Release notes are linked', /Release notes/);
  await t.click(S.approve, 'Approve 3 tickets', approvedOpts);
  await t.expectText('Bob approved and the tickets were created', /Bob approved, and the platform created the tickets/);
}, [1280, 390]);

add('C-self', 'Alice turns on a workflow, does a test run, and cannot approve her own test run', async (t) => {
  await t.click(S.example(0), 'Tap the first example', { reply: true });
  await t.field(S.time, '17:00', 'Choose the time', { decision: true });
  await t.select(S.project, 'MOCK', 'Choose the Jira project', { decision: true });
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.click(S.testRun, 'Do a test run', { until: /You started this run, so you can’t approve it/ });
  await t.expectText('The page says Alice cannot approve her own run', /You started this run, so you can’t approve it\. Nobody approves their own work\./);
  await t.expectCount('There is no Approve button for her', '[data-act="approve"][data-arg="conf"]', 0);
});

/* D. Unsupported request. */
add('D', 'An Operator asks to email a weekly list, and the limit is explained with an alternative', async (t) => {
  await t.ask(EMAIL, 'email me a list of open bugs every Monday');
  await t.expectText('The Planner says it cannot send email', /I can’t send email yet\. Email isn’t connected to the platform/);
  await t.expectText('An alternative is offered', /What I can do instead[\s\S]*The same thing, with the result put in one Jira ticket, after a yes\./);
  await t.expectCount('Set that up is offered', '[data-act="instead"]', 1);
  await t.expectCount('Ask the team is offered', '[data-act="teamReq"]:has-text("Ask the team")', 1);
});

/* E. Misunderstanding, corrected on the card. */
add('E', 'The user corrects the Planner’s guess of project and schedule on the card, without starting again', async (t) => {
  await t.ask('Every Friday at 17:00, sum up the tickets we closed this week in project MOCK', 'a request the Planner reads as MOCK and Friday');
  await t.expectText('The card starts with MOCK and Friday', /Every Friday at 17:00[\s\S]*MOCK/);
  await t.select(S.project, 'OPS', 'Correct the Jira project', { decision: true });
  await t.click('[data-act="whenOpen"]', 'Open the schedule');
  await t.select('#sched-day', 'Monday', 'Correct the day', { decision: true });
  await t.click('[data-act="whenDone"]', 'Close the schedule');
  await t.expect('The card now says OPS', t.page.innerText('.pcard .sentence-line'), /OPS/);
  await t.expect('The card now says Monday', t.page.innerText('.pcard .sentence-line'), /Every Monday at 17:00/);
  await t.expectCount('Still one set-up card, nothing started again', '.pcard:has([data-act="turnOn"])', 1);
  await t.expect('Still one request in the chat', t.page.innerText('main'), (v) => (v.match(/You:/g) || []).length === 1);
  await t.expectCount('Turn it on is ready', '[data-act="turnOn"]:not([disabled])', 1);
});

/* F. Failed run. */
add('F', 'Recover the stop the user can fix, and report the platform bug to support', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.fixIt, 'See why and fix it');
  await t.click(S.retry, 'Use langchain-ai/langchain and retry', { decision: true, until: /The workflow now reads langchain-ai\/langchain/ });
  await t.expectText('The fixable stop is fixed', /Fixed/);
  await t.menu('workflows', 'Back to Workflows');
  await t.expectText('The platform bug is still stopped, with Report to support', /Stale ticket nudge[\s\S]*Report to support/);
  await t.click(`main ${S.report}`, 'Report to support');
  await t.expectText('The report dialog shows what the AI troubleshooter found', /The AI troubleshooter found[\s\S]*has no owner/, '.dialog');
  await t.click(S.sendReport, 'Send report', { decision: true });
  await t.expectText('Support gives a case reference', /SUP-1042/, '.dialog');
  await t.click(S.doneDialog, 'Done');
  await t.expectText('The case is followed on Workflows', /Following up/);
}, [1280]);

/* G. Software monitoring. */
add('G', 'Monitor Kubernetes releases from Home ends with Kubernetes on the Software watchlist', async (t) => {
  await t.ask('Monitor Kubernetes releases', 'Monitor Kubernetes releases');
  await t.expectText('The Planner sends it to the Software watchlist', /this belongs on the Software watchlist/);
  await t.click('[data-act="repoOk"]', 'Looks right', { decision: true });
  await t.click('[data-act="verNewest"]', 'Not sure? Start from the newest');
  await t.click('[data-act="watchAdd"]', 'Add Kubernetes', { decision: true });
  await t.expectText('The Planner confirms it', /Kubernetes is on the Software watchlist/);
  await t.setup((k) => k.go('software'));
  await t.expectText('Kubernetes is on the Software watchlist page', /Not checked yet[\s\S]*Kubernetes/);
});

/* H. Workflow management. */
add('H', 'Pause a workflow, change its schedule, and delete one with its confirmation', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning bug report check');
  await t.click('[data-act="editSched"]', 'Change schedule');
  await t.select('#sf-freq', 'week', 'How often', { decision: true });
  await t.select('#sf-day', 'Friday', 'Day', { decision: true });
  await t.field('#sf-time', '09:30', 'Time', { decision: true });
  await t.click('[data-act="saveSched"]', 'Save the schedule');
  await t.expectText('The schedule is saved', /Saved\. Next run/, S.toast);
  await t.expectText('The page shows the new schedule', /Every Friday at 9:30/);
  await t.click('[data-act="pause"]', 'Pause', { decision: true });
  await t.expectText('The workflow is paused', /Paused\. Morning bug report check won’t run until you resume it/, S.toast);
  await t.expectCount('A Resume button replaces Pause', '[data-act="resume"]', 1);
  await t.click('main [data-act="go"][data-arg="workflows"]', 'Back to Workflows');
  await t.click(S.row('nudge'), 'Open Stale ticket nudge');
  await t.click('[data-act="askDelete"]', 'Delete');
  await t.expectText('A confirmation asks first', /Delete Stale ticket nudge\?[\s\S]*Its past runs stay in the record/, '.dialog');
  await t.click('[data-act="confirmDelete"]', 'Delete workflow', { decision: true });
  await t.expectText('It is deleted, with Undo', /Deleted Stale ticket nudge\.\s*Undo/, S.toast);
  await t.expectCount('It is gone from Workflows', 'main [data-act="workflow"][data-arg="nudge"]', 0);
});

/* The fifteen tasks in 03b section 6. */
const T = (n, title, run, extra) => add(`T${n}`, title, run, [1280], extra);

T(1, 'Set up a workflow from example 1: example, time, Jira project, Turn it on', async (t) => {
  await t.click(S.example(0), 'Tap the first example', { reply: true });
  await t.field(S.time, '17:00', 'Choose the time', { decision: true });
  await t.select(S.project, 'MOCK', 'Choose the Jira project', { decision: true });
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Weekly stale ticket list is on/);
});

T(2, 'Set up a typed workflow with every part stated: type, Enter, Turn it on', async (t) => {
  await t.ask('Every Friday at 17:00, list the open tickets with no update for 10 days in project MOCK', 'a request with every part stated');
  await t.expectText('Nothing is unclear', /Nothing is unclear\. One yes turns it on\./);
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /is on\./);
});

T(3, 'Do a test run after turning one on', async (t) => {
  await t.setup(turnOnWeekly);
  await t.click(S.testRun, 'Do a test run', { until: /Alice started a test run/ });
  await t.expectText('A test run is under way', /Alice started a test run/);
});

T(4, 'Add software from Home with example 3: example, Looks right, Start from the newest, Add React', async (t) => {
  await t.click(S.example(2), 'Tap the third example', { reply: true });
  await t.click('[data-act="repoOk"]', 'Looks right', { decision: true });
  await t.click('[data-act="verNewest"]', 'Not sure? Start from the newest');
  await t.click('[data-act="watchAdd"]', 'Add React', { decision: true });
  await t.expectText('React is on the Software watchlist', /React is on the Software watchlist/);
});

T(5, 'Add software on the Software watchlist page', async (t) => {
  await t.menu('software', 'Open Software watchlist');
  await t.field('#sw-name', 'Prometheus', 'Name');
  await t.field('#sw-repo', 'prometheus/prometheus', 'GitHub repository');
  await t.click('[data-act="addSoftware"]', 'Add');
  await t.expectText('Prometheus is added', /Added Prometheus/, S.toast);
});

T(6, 'Approve from Workflows: Workflows, Review and decide, Approve 3 tickets', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.review, 'Review and decide');
  await t.click(S.approve, 'Approve 3 tickets', approvedOpts);
  await t.expectText('The tickets were created', /Alice approved, and the platform created the tickets/);
});

T(7, 'Approve from Home as an Approver only: Review and decide, Approve', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click(S.approve, 'Approve 3 tickets', approvedOpts);
  await t.expectText('The tickets were created', /Bob approved, and the platform created the tickets/);
});

T(8, 'Approve from the Teams drawer: Teams, Approve', async (t) => {
  await t.click(S.teams, 'Open Teams');
  await t.click('.drawer [data-act="approve"][data-arg="sw"]', 'Approve', { decision: true });
  await t.expectText('The drawer shows the yes was recorded', /Approved by Alice/, '.drawer');
});

T(9, 'Fix a stopped run the user can fix: Workflows, See why and fix it, retry', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.fixIt, 'See why and fix it');
  await t.click(S.retry, 'Use langchain-ai/langchain and retry', { decision: true, until: /The workflow now reads langchain-ai\/langchain/ });
  await t.expectText('The run is fixed', /Fixed/);
});

T(10, 'Report a platform bug: Workflows, Report to support, Send report, Done', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(`main ${S.report}`, 'Report to support');
  await t.click(S.sendReport, 'Send report', { decision: true });
  await t.expectText('Support gives a case reference', /SUP-1042/, '.dialog');
  await t.click(S.doneDialog, 'Done');
  await t.expectText('The case shows on Workflows', /Following up/);
});

T(11, 'Pause a workflow: Workflows, row, Pause', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('access'), 'Open Quarterly access review');
  await t.click('[data-act="pause"]', 'Pause', { decision: true });
  await t.expectText('The workflow is paused', /Paused\. Quarterly access review won’t run until you resume it/, S.toast);
});

T(12, 'Delete a workflow: Workflows, row, Delete, Delete workflow', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('nudge'), 'Open Stale ticket nudge');
  await t.click('[data-act="askDelete"]', 'Delete');
  await t.click('[data-act="confirmDelete"]', 'Delete workflow', { decision: true });
  await t.expectText('It is deleted, with Undo', /Deleted Stale ticket nudge\.\s*Undo/, S.toast);
});

T(13, 'Change who approves: Workflows, row, Change who approves, Save', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning bug report check');
  await t.click('[data-act="editAppr"]', 'Change who approves');
  await t.select('#af-first-0', 'arun', 'Asked first', { decision: true });
  await t.select('#af-backup-0', 'siti', 'Backup', { decision: true });
  await t.click('[data-act="saveAppr"]', 'Save');
  await t.expectText('Arun is asked first from the next run', /Saved\. From the next run, Arun is asked first/, S.toast);
});

T(14, 'Change an agent in plain English: Agent library, Details and changes, chip, Suggest a change, Save', async (t) => {
  await t.menu('agents', 'Open Agent library');
  await t.click('[data-act="agent"][data-arg="writer"]:has-text("Details and changes")', 'Ticket writer: Details and changes');
  await t.click('[data-act="agentChip"]', 'Pick a suggested change');
  await t.click('[data-act="agentSuggest"]', 'Suggest a change');
  await t.click('[data-act="agentSave"]', 'Save as version 2', { decision: true });
  await t.expectText('Saved as version 2', /Saved as version 2\. Ticket writer uses it from the next run/, S.toast);
});

T(15, 'Ask the team for a new system, after a "can’t" answer', async (t) => {
  await t.setup((k) => k.ask(EMAIL));
  await t.click('[data-act="teamReq"]:has-text("Ask the team")', 'Ask the team', { decision: true });
  await t.expectText('The request is sent to the team', /Sent to the team\. You can follow it on Tools, in the Agent library\./, S.toast);
});

/* Not possible in version 3. Recorded so version 4 can show it. */
add('H2', 'Discard a draft set-up card from Workflows', async () => {}, [1280], {
  notPossible: 'Version 3 has no control that removes a draft. Only opening it (openDraft) or turning it on takes it off the list (03b section 4.7).',
});

/* Screens shot by shots.cjs and measured by quality.cjs. prepare(k) sets the screen up like a user would reach it. */
const open = async (k, sel) => { await k.page.click(sel); await k.settle(); };
const screens = [
  { name: 'day-one-home', prepare: async (k) => { await k.setDay('one'); } },
  { name: 'home', prepare: async () => {} },
  { name: 'approver-home', prepare: async (k) => { await k.setUser('bob'); } },
  { name: 'planner-setup-card', prepare: async (k) => { await k.ask(WEEKLY_SUMMARY); } },
  { name: 'planner-cant-email', prepare: async (k) => { await k.ask(EMAIL); } },
  { name: 'planner-watch-kubernetes', prepare: async (k) => { await k.ask('Monitor Kubernetes releases'); } },
  { name: 'workflows', prepare: async (k) => { await k.go('workflows'); } },
  { name: 'workflow-page', prepare: async (k) => { await k.go('workflows'); await open(k, S.row('issues')); } },
  { name: 'run-stopped', prepare: async (k) => { await k.go('workflows'); await open(k, S.fixIt); } },
  { name: 'run-approval', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); } },
  { name: 'software', prepare: async (k) => { await k.go('software'); } },
  { name: 'agent-library', prepare: async (k) => { await k.go('agents'); } },
  { name: 'agent-library-tools', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="libTab"][data-arg="tools"]'); } },
  { name: 'settings-connections', prepare: async (k) => { await open(k, '.hdr [data-act="go"][data-arg="settings"]'); await open(k, '[data-act="setTab"][data-arg="connections"]'); } },
  { name: 'teams-drawer', prepare: async (k) => { await open(k, S.teams); } },
  { name: 'drafts', prepare: async (k) => { await k.ask(WEEKLY_SUMMARY); await open(k, '[data-act="newChat"]'); await k.go('workflows'); } },
];

module.exports = {
  version: 'v3',
  scenarios,
  screens,
  /* The keyboard check in quality.cjs: the control a keyboard user must reach on Home. */
  keyboard: { operatorTarget: '[data-ask]', approverTarget: '[data-act="run"][data-arg="sw"]' },
  /* Which controls open the Teams drawer and the test controls, so shots and quality can leave them out. */
  hide: '.testctl, .toast',
};
