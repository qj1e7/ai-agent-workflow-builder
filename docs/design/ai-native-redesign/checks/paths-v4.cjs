/* Paths for version 4, docs/design/ai-native-redesign/prototype.html.
   Copied from paths-v3.cjs. The ids are the same, each doing the same user task the version 4 way, with the same
   counting rules and the same decision tags. A scenario whose task changed on purpose carries `changed: 'why'`. */

const CHECK_WORKFLOWS = 'Check my workflows';
const WEEKLY_SUMMARY = 'every Friday, sum up the tickets we closed this week';
const EMAIL = 'email me a list of open bugs every Monday';

/* Selectors */
const S = {
  ask: '[data-ask]',
  example: (i) => `main [data-act="example"][data-arg="${i}"]`,
  start: (i) => `main .thread [data-act="say"] >> nth=${i}`,
  time: '#sched-time',
  project: '#fix-project',
  /* The set-up card asks one question at a time, with choice buttons (ADR 0043). */
  answer: (arg) => `main .thread [data-act="answer"][data-arg="${arg}"]`,
  asks: 'main .thread .part[data-mark="ask"]',
  turnOn: '[data-act="turnOn"]',
  testRun: '[data-act="testRun"]',
  review: 'main [data-act="run"][data-arg="sw"]:has-text("Review and decide")',
  approve: '[data-act="approve"][data-arg="sw"]',
  retry: 'main [data-act="retryIssues"]',
  seeRun: 'main [data-act="run"][data-arg="issues"]:has-text("See the run")',
  report: '[data-act="report"]',
  sendReport: '[data-act="sendReport"]',
  doneDialog: '.dialog [data-act="closeModal"]',
  row: (id) => `main [data-act="workflow"][data-arg="${id}"]`,
  more: 'main [data-act="menu"]',
  pick: (act, id) => `.menu [data-act="menuPick"][data-arg="${act}:${id}"]`,
  teams: '.hdr [data-act="teams"]',
  toast: '.toast',
};

/* Test controls by their data-act, or a simulation by its words. Never counted. The runner's sim() looks for a
   v3 class (.testctl-sims) that version 4 does not have, so these go through the panel directly. */
async function ctl(k, act, arg) {
  const open = !!(await k.page.$('.testctl-panel'));
  if (!open) await k.page.$eval('.testctl-toggle', (b) => b.click());
  const sel = arg === undefined ? `.testctl button:has-text("${act}")` : `.testctl [data-act="${act}"][data-arg="${arg}"]`;
  await k.page.$eval(sel, (b) => b.click()).catch(() => { throw new Error(`test control not found: ${act} ${arg || ''}`); });
  if (await k.page.$('.testctl-panel')) await k.page.$eval('.testctl-toggle', (b) => b.click());
  await k.settle();
}

/* The same set-up as a user would do it, without counting it. The card asks the time, then the Jira project. */
async function turnOnWeekly(k) {
  await k.ask(WEEKLY_SUMMARY);
  await k.page.click(S.answer('time:17:00'));
  await k.settle();
  await k.page.click(S.answer('project:MOCK'));
  await k.settle();
  await k.page.click(S.turnOn);
  await k.settle(600);
}
const ONE_QUESTION = 'one question at a time with choice buttons (ADR 0043)';

const approvedText = /approved, and the platform created the tickets/;
const approvedOpts = { decision: true, until: approvedText };
const retriedText = /Done, nothing new today/;

/* Keyboard focus starts at the top of the page, as after a load. Test controls move it, so this resets it. */
const focusTop = (k) => k.page.evaluate(() => {
  const probe = document.createElement('span');
  probe.tabIndex = -1;
  document.body.prepend(probe);
  probe.focus();
  probe.remove();
});
const focused = (page) => page.evaluate(() => {
  const el = document.activeElement;
  return el ? `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${el.dataset && el.dataset.act ? `[${el.dataset.act}${el.dataset.arg ? `=${el.dataset.arg}` : ''}]` : ''}` : '';
});
/* Press Tab until the focused element matches, counting every press. Fails if it takes more than max presses. */
async function tabTo(t, sel, label, max = 30) {
  for (let i = 0; i < max; i += 1) {
    await t.press('Tab', `Tab towards ${label}`);
    if (await t.page.evaluate((s) => !!document.activeElement && document.activeElement.matches(s), sel)) return;
  }
  throw new Error(`Tab did not reach ${label} in ${max} presses (at ${await focused(t.page)})`);
}

const scenarios = [];
const add = (id, title, run, viewports = [1280], extra = {}) => viewports.forEach((viewport) => scenarios.push({ id, title, viewport, run, ...extra }));

/* A. First-time Operator, day one. */
add('A', 'First-time Operator sets up a weekly Jira summary and turns it on', async (t) => {
  await t.setup((k) => k.setDay('one'));
  await t.expectText('Day one Home asks which software to keep up to date', /Which software should we keep up to date\?/);
  await t.ask(WEEKLY_SUMMARY, 'every Friday, sum up the tickets we closed this week');
  const left = await t.page.innerText('main');
  const asks = Number((left.match(/(\d+) choices? left/) || [0, 0])[1]);
  t.metric('plannerQuestions', asks);
  await t.expect('The Planner asks back for when it runs and the Jira project', left, /2 choices left: when it runs and the Jira project/);
  await t.expectCount('It asks one of them now', S.asks, 1);
  await t.click(S.answer('time:17:00'), 'Choose 17:00', { decision: true });
  await t.click(S.answer('project:MOCK'), 'Choose MOCK', { decision: true });
  await t.expectText('Nothing is unclear before turning on', /Nothing is unclear\. Turn it on when you’re ready\./);
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Friday closed ticket summary is on/);
}, [1280, 390], { changed: `The card asks ${ONE_QUESTION}: the time, then the Jira project. Each is one tap, where version 4 had a select and a typed time.` });

/* B. Experienced Operator, a normal week. Through Workflows, as in version 3. B-home does it from Home. */
add('B', 'Experienced Operator finds what needs attention and fixes the stopped Morning new-ticket check', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Needs you lists five things, the moved LangServe project among them', /Needs you\s+5[\s\S]*GitHub can’t find/);
  await t.expectText('The stopped Morning new-ticket check is listed with what happened and a fix', /Morning new-ticket check stopped[\s\S]*Jira didn’t answer at 8:00\. It’s answering again[\s\S]*A retry reads the tickets again[\s\S]*Retry the run/);
  await t.click(S.retry, 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The retry finished', retriedText);
  await t.setup((k) => k.go('workflows'));
  await t.expectText('Morning new-ticket check is no longer stopped', /Morning new-ticket check\s+Finds[^\n]*\s+On\s+Next run/);
  await t.expect('No stopped Morning new-ticket check left', t.page.innerText('main'), (v) => !/Morning new-ticket check stopped/.test(v));
}, [1280, 390], { changed: 'The sample stop is now Jira not answering (I2), fixed by a retry. The troubleshooter’s answer is on Workflows itself, so the run page is no longer a step.' });

/* C. Approver. */
add('C', 'Bob, an Approver only, opens the upgrade request, sees what changes and the evidence, and approves', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.expectText('Bob sees one request that needs him', /1 request is waiting for your yes/);
  await t.click(S.review, 'Review and decide');
  await t.expectText('The page says what will be written', /3 tickets will be created in Jira project MOCK/);
  await t.expectText('The page says nothing else is written', /exactly what will be written, and nothing else/);
  await t.expectText('The evidence is there: each upgrade with what its release says', /Upgrade Log4j core from 2\.14\.1 to 2\.25\.2[\s\S]*Security fixes and bug fixes/);
  await t.expectText('Release notes are linked', /Release notes/);
  await t.click(S.approve, 'Approve', approvedOpts);
  await t.expectText('Bob approved and the tickets were created', /Bob approved, and the platform created the tickets/);
}, [1280, 390], { changed: 'The NVD and CISA evidence came from ADR 0025 sources, which are Planned and hidden by default (I9). The evidence is the GitHub release notes.' });

add('C-self', 'Alice turns on a workflow, does a test run, and cannot approve her own test run', async (t) => {
  await t.ask(WEEKLY_SUMMARY, 'every Friday, sum up the tickets we closed this week');
  await t.click(S.answer('time:17:00'), 'Choose 17:00', { decision: true });
  await t.click(S.answer('project:MOCK'), 'Choose MOCK', { decision: true });
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.click(S.testRun, 'Do a test run', { until: /another Approver must decide/ });
  await t.expectText('The page says Alice cannot approve her own run', /You set this up and started this run, so another Approver must decide\. Nobody approves their own work\./);
  await t.expectCount('There is no Approve button for her', '[data-act="approve"][data-arg="conf"]', 0);
}, [1280], { changed: `Home no longer suggests a general workflow (8 Nov, software versioning first), so she types the request, as in scenario A. The card asks ${ONE_QUESTION}.` });

/* D. Unsupported request. */
add('D', 'An Operator asks to email a weekly list, and the limit is explained with a next step', async (t) => {
  await t.ask(EMAIL, 'email me a list of open bugs every Monday');
  await t.expectText('The Planner says it cannot send email', /I can’t send email\. Email isn’t on the team’s plan\. Ask the team if you need it\./);
  await t.expectCount('No alternative is offered, because a list of bugs needs the ticket type', '[data-act="instead"]', 0);
  await t.expectCount('Ask the team is the next step', '[data-act="teamReq"]:has-text("Ask the team")', 1);
}, [1280], { changed: 'An alternative is offered only when it sets up cleanly (review item 2). “Open bugs” needs the ticket type, which agents can’t see, so the only next step is Ask the team.' });

/* E. Misunderstanding, corrected on the card. */
add('E', 'The user corrects the Planner’s guess of project and schedule on the card, without starting again', async (t) => {
  await t.ask('Every Friday at 17:00, sum up the tickets we closed this week in project MOCK', 'a request the Planner reads as MOCK and Friday');
  await t.expectText('The card starts with MOCK and Friday', /Every Friday at 17:00[\s\S]*MOCK/);
  await t.select(S.project, 'OPS', 'Correct the Jira project', { decision: true });
  await t.click('[data-act="whenOpen"]', 'Open the schedule');
  await t.select('#sched-day', 'Monday', 'Correct the day', { decision: true });
  await t.click('[data-act="whenDone"]', 'Close the schedule');
  await t.expect('The card now says OPS', t.page.innerText('.pcard .parts'), /OPS/);
  await t.expect('The card now says Monday', t.page.innerText('.pcard .parts'), /Every Monday at 17:00/);
  await t.expectCount('Still one set-up card, nothing started again', '.pcard:has([data-act="turnOn"])', 1);
  await t.expect('Still one request in the chat', t.page.innerText('main'), (v) => (v.match(/You:/g) || []).length === 1);
  await t.expectCount('Turn it on is ready', '[data-act="turnOn"]:not([disabled])', 1);
}, [1280], { changed: 'The same steps. The card’s one sentence became a list of parts (ADR 0043), so the check reads the list.' });

/* F. Failed run. */
add('F', 'Recover the stop the user can fix, and report the platform bug to support', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.retry, 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The fixable stop is fixed', retriedText);
  await t.menu('workflows', 'Back to Workflows');
  await t.expectText('The platform bug is still stopped, with Report to support', /Weekly closed-ticket summary stopped[\s\S]*Report to support/);
  await t.click(`main ${S.report}`, 'Report to support');
  await t.expectText('The report dialog shows what the AI troubleshooter found', /The AI troubleshooter found[\s\S]*MOCK-31/, '.dialog');
  await t.click(S.sendReport, 'Send report', { decision: true });
  await t.expectText('Support gives a case reference', /SUP-1042/, '.dialog');
  await t.click(S.doneDialog, 'Done');
  await t.expectText('The case is followed on Workflows', /Following up/);
}, [1280], { changed: 'The fixable stop is a retry (I2), offered on Workflows, so the run page is no longer a step.' });

/* G. Software monitoring. */
add('G', 'Monitor Kubernetes releases from Home ends with Kubernetes on the Software watchlist', async (t) => {
  await t.ask('Monitor Kubernetes releases', 'Monitor Kubernetes releases');
  await t.expectText('The Planner sends it to the Software watchlist', /this belongs on the Software watchlist/);
  await t.click('[data-act="repoOk"]', 'Looks right', { decision: true });
  await t.click('[data-act="verNewest"]', 'Not sure? Start from the newest');
  await t.click('[data-act="watchAdd"]', 'Add Kubernetes', { decision: true });
  await t.expectText('The Planner confirms it', /Kubernetes is on the Software watchlist/);
  await t.setup((k) => k.go('software'));
  await t.expectText('Kubernetes is on the Software watchlist page', /Kubernetes[\s\S]{0,200}Not checked yet/);
});

/* H. Workflow management. */
add('H', 'Pause a workflow, change its schedule, and delete one with its confirmation', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('main [data-act="editSched"][data-arg="issues"]', 'Change schedule');
  await t.select('#sf-freq', 'week', 'How often', { decision: true });
  await t.select('#sf-day', 'Friday', 'Day', { decision: true });
  await t.field('#sf-time', '09:30', 'Time', { decision: true });
  await t.click('[data-act="saveSched"]', 'Save the schedule');
  await t.expectText('The schedule is saved', /Saved\. Next run/, S.toast);
  await t.expectText('The page shows the new schedule', /Every Friday at 9:30/);
  await t.click('main [data-act="pause"][data-arg="issues"]', 'Pause', { decision: true });
  await t.expectText('The workflow is paused', /Paused\. Morning new-ticket check won’t run until you resume it/, S.toast);
  await t.expectCount('Pause is gone', 'main [data-act="pause"]', 0);
  await t.expectCount('One Resume button replaces Pause (spec 8: no page offers the same button twice)', 'main [data-act="resume"]', 1);
  await t.click('main [data-act="go"][data-arg="workflows"]', 'Back to Workflows');
  await t.click(S.row('nudge'), 'Open Weekly closed-ticket summary');
  await t.click(S.more, 'More actions');
  await t.click(S.pick('askDelete', 'nudge'), 'Delete');
  await t.expectText('A confirmation asks first', /Delete Weekly closed-ticket summary\?[\s\S]*Its past runs and their records stay/, '.dialog');
  await t.click('[data-act="confirmDelete"]', 'Delete workflow', { decision: true });
  await t.expectText('It is deleted, with Undo', /Deleted Weekly closed-ticket summary\.\s*Undo/, S.toast);
  await t.expectCount('It is gone from Workflows', 'main [data-act="workflow"][data-arg="nudge"]', 0);
}, [1280], { changed: 'Delete moved into the More actions menu (spec 9), one tap more. Pause is a button beside it.' });

/* The fifteen tasks in 03b section 6. */
const T = (n, title, run, extra) => add(`T${n}`, title, run, [1280], extra);

T(1, 'Set up a workflow from example 1: example, time, Jira project, Turn it on', async () => {}, { notPossible: 'Since 8 Nov the starting points under “Set up another workflow” are software versioning only (Keep track of the React version). None sets up a general Jira workflow, so there is no example to tap. Typing the same request is scenario T2.' });

T(2, 'Set up a typed workflow with every part stated: type, Enter, Turn it on', async (t) => {
  await t.ask('Every Friday at 17:00, sum up the tickets we closed this week in project MOCK', 'a request with every part stated');
  await t.expectText('Nothing is unclear', /Nothing is unclear\. Turn it on when you’re ready\./);
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /is on\./);
}, { changed: 'The v3 request needs a ticket’s update date, which the Jira tool can’t see (UX audit X2), so v4 answers “Part I can do”. The typed request is one the tools can do.' });

T(3, 'Do a test run after turning one on', async (t) => {
  await t.setup(turnOnWeekly);
  await t.click(S.testRun, 'Do a test run', { until: /Who asked[\s\S]*Alice started a test run/ });
  await t.expectText('A test run is under way', /Test run[\s\S]*Alice started a test run/);
});

T(4, 'Add software from Home with example 3: example, Looks right, Start from the newest, Add React', async (t) => {
  await t.ask('Set up another workflow', 'Set up another workflow');
  await t.click(`main .thread [data-act="say"][data-arg="Keep track of the React version"]`, 'Tap Keep track of the React version', { reply: true });
  await t.click('[data-act="repoOk"]', 'Looks right', { decision: true });
  await t.click('[data-act="verNewest"]', 'Not sure? Start from the newest');
  await t.click('[data-act="watchAdd"]', 'Add React', { decision: true });
  await t.expectText('React is on the Software watchlist', /React is on the Software watchlist/);
}, { changed: 'The React example sits behind “Set up another workflow”, which is no longer a suggestion on Home, so she types it (spec 5.1).' });

T(5, 'Add software on the Software watchlist page', async (t) => {
  await t.menu('software', 'Open Watchlist');
  await t.field('#sw-name', 'Prometheus', 'Name');
  await t.click('main form[data-submit="swFind"] button[type="submit"]', 'Find it');
  await t.field('#sw-repo', 'prometheus/prometheus', 'GitHub repository');
  await t.click('main form[data-submit="swAdd"] button[type="submit"]', 'Add Prometheus');
  await t.expectText('Prometheus is added', /Added Prometheus/, S.toast);
}, { changed: 'Add software takes plain words and looks the project up first (spec 11). Prometheus is not a known project, so it then asks for the repository.' });

T(6, 'Approve from Workflows: Workflows, Review and decide, Approve 3 tickets', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.review, 'Review and decide');
  await t.click(S.approve, 'Approve', approvedOpts);
  await t.expectText('The tickets were created', /Alice approved, and the platform created the tickets/);
});

T(7, 'Approve from Home as an Approver only: Review and decide, Approve', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click(S.approve, 'Approve', approvedOpts);
  await t.expectText('The tickets were created', /Bob approved, and the platform created the tickets/);
});

T(8, 'Approve from the Teams drawer: Teams, Approve', async (t) => {
  await t.click(S.teams, 'Open Teams');
  await t.expectCount('The drawer has no Approve or Decline', '.drawer :is([data-act="approve"], [data-act="decline"])', 0);
  await t.click('.drawer [data-act="run"][data-arg="sw"]', 'Open in AI Workflow Builder');
  await t.click(S.approve, 'Approve', approvedOpts);
  await t.expectText('The page shows the yes was recorded', /Alice approved, and the platform created the tickets/);
  await t.setup(async (k) => { await k.page.click(S.teams); await k.settle(); });
  await t.expectText('The drawer shows the decision read from the platform', /Approved by Alice/, '.drawer');
}, { changed: 'ADR 0036: Teams carries the request and its one button opens the approval page. Nobody approves inside Teams.' });

T(9, 'Fix a stopped run the user can fix: Workflows, See why and fix it, retry', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.retry, 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The run is fixed', retriedText);
}, { changed: 'The user-fixable stop is Jira not answering, fixed by a retry offered on Workflows. The moved GitHub project is now a watchlist item (Use the new address).' });

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
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('main [data-act="pause"][data-arg="issues"]', 'Pause', { decision: true });
  await t.expectText('The workflow is paused', /Paused\. Morning new-ticket check won’t run until you resume it/, S.toast);
}, { changed: 'The quarterly access review is Planned and hidden by default (I2), so another workflow is paused.' });

T(12, 'Delete a workflow: Workflows, row, Delete, Delete workflow', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('nudge'), 'Open Weekly closed-ticket summary');
  await t.click(S.more, 'More actions');
  await t.click(S.pick('askDelete', 'nudge'), 'Delete');
  await t.click('[data-act="confirmDelete"]', 'Delete workflow', { decision: true });
  await t.expectText('It is deleted, with Undo', /Deleted Weekly closed-ticket summary\.\s*Undo/, S.toast);
}, { changed: 'Delete is last in the More actions menu, after a divider (spec 9).' });

T(13, 'Change who approves: Workflows, row, Change who approves, Save', async (t) => {
  await t.setup((k) => ctl(k, 'preview', 'on'));
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('[data-act="editAppr"]', 'Change who approves');
  await t.select('#af-first-0', 'arun', 'Asked first', { decision: true });
  await t.select('#af-backup-0', 'siti', 'Backup', { decision: true });
  await t.click('[data-act="saveAppr"]', 'Save');
  await t.expectText('Arun is asked first from the next run', /Saved\. From the next run, Arun is asked first/, S.toast);
}, { changed: 'Named Approvers are ADR 0024, which is not built. The task exists only with Planned features shown, tagged Planned (I4).' });

T(14, 'Change an agent in plain English: Settings, How it works, Details and changes, chip, Suggest a change, Save', async (t) => {
  await t.setup((k) => ctl(k, 'preview', 'on'));
  await t.menu('agents', 'Open Settings');
  await t.click('[data-act="setTab"][data-arg="how"]', 'Open How it works');
  await t.click('[data-act="libTab"][data-arg="agents"]', 'Open the Agents tab');
  await t.click('[data-act="agent"][data-arg="writer"]:has-text("Details and changes")', 'Ticket writer: Details and changes');
  await t.expectCount('Changing an agent is tagged Planned in its dialog', '.dialog .tag.planned', (n) => n >= 1);
  await t.click('[data-act="agentChip"]', 'Pick a suggested change');
  await t.click('[data-act="agentSuggest"]', 'Suggest a change');
  await t.click('[data-act="agentSave"]', 'Save as version 2', { decision: true });
  await t.expectText('Saved as version 2', /Saved as version 2\. Ticket writer uses it from the next run/, S.toast);
}, { changed: 'Changing an agent in plain English is Planned (handover L04) and the agent dialog is read only by default, so the task exists only with Planned features shown, tagged Planned. The Agent library opens on “What it can do” (spec 12), so the agents are one tab away.' });

T(15, 'Ask the team for a new system, after a "can’t" answer', async (t) => {
  await t.setup((k) => k.ask(EMAIL));
  await t.click('[data-act="teamReq"]:has-text("Ask the team")', 'Ask the team', { decision: true });
  await t.expectText('The request is saved for the team', /Saved as a request for the team\. You can follow it on Tools, under How it works in Settings\./, S.toast);
}, { changed: 'Fix round D, F-01: nobody is named yet as the reader of team requests (ADR 0038, proposed), so the confirmation no longer says it was sent to anyone. Was /Sent to the team\. You can follow it on Tools, under How it works in Settings\./.' });

add('H2', 'Discard a draft set-up card from Workflows', async (t) => {
  await t.setup(async (k) => { await k.ask(WEEKLY_SUMMARY); await k.page.click('[data-act="newChat"]'); await k.settle(); });
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('The draft is listed with what it lacks', /Drafts\s+1[\s\S]*Needs when it runs and the Jira project/);
  await t.click('main [data-act="discardDraft"]', 'Discard', { decision: true });
  await t.expectCount('Undo is offered', '.toast [data-act="undoDiscard"]', 1);
  await t.expect('The draft is gone', t.page.innerText('main'), (v) => !/Drafts\s+\d/.test(v));
}, [1280], { changed: 'New in version 4. Version 3 had no way to remove a draft.' });

/* New tasks in version 4. */
add('B-home', 'Find and act on the stopped workflow from Home’s Needs you', async (t) => {
  await t.expectText('Home lists the stopped workflow first, with its fix', /Needs you\s+5\s+Do now\s+Morning new-ticket check stopped\s+Jira didn’t answer at 8:00\.\s+Retry the run/);
  await t.click(S.retry, 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The retry finished', retriedText);
  await t.setup((k) => k.go('home'));
  await t.expectText('Home now has four things', /Needs you\s+4\b/);
  await t.expect('The stopped row is gone from Home', t.page.innerText('main'), (v) => !/Morning new-ticket check stopped/.test(v));
}, [1280, 390], { changed: 'Needs you is grouped into Do now and Set up (ADR 0043), so the Do now heading comes before the first row.' });

add('ASK-status', '“Check my workflows” typed to the Planner', async (t) => {
  await t.ask(CHECK_WORKFLOWS, 'Check my workflows');
  await t.expectText('The Planner sums up every workflow', /You have 3 workflows\. 2 stopped and 1 is waiting for a yes\./, 'main .thread');
  await t.expectCount('One row per workflow', 'main .thread [data-act="workflow"]', 3);
  await t.expectText('Each row has its status, next run and one action', /Morning new-ticket check\s+Stopped\s+Next run[^\n]*\s+Retry the run[\s\S]*Keep our software up to date\s+Waiting for a yes\s+Next run[^\n]*\s+Review and decide/, 'main .thread');
}, [1280, 390]);

add('ASK-why', '“Why did Morning new-ticket check stop?” ending in a retry from the answer', async (t) => {
  await t.expect('No Why chip for the stop that is already the first Needs you row', t.page.innerText('main .examples'), (v) => !/Why did Morning new-ticket check stop/.test(v));
  await t.ask('Why did Morning new-ticket check stop?');
  await t.expectText('The three answers', /What happened[\s\S]*What was affected[\s\S]*Safe to retry/, 'main .thread');
  await t.click('main .thread [data-act="retryIssues"]', 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The retry finished', retriedText);
}, [1280], { changed: 'Home offers no Why chip for a stop that is already the first Needs you row (review item 8), so the question is typed. ADR 0043 step 3: the troubleshooter gives three answers, and What to do is the Retry button under them. Was /What happened…What was affected…Can it be fixed safely…What to do/.' });

add('ASK-needs', '“What needs me?”', async (t) => {
  await t.ask('What needs me?');
  await t.expectText('The Planner counts what needs her', /5 things need you\./, 'main .thread');
  await t.expectCount('One Needs you row per thing in the answer', 'main .thread li.nrow', 5);
}, [1280]);

add('OFFLINE', 'No AI model: Home says so and offers Connect a model', async (t) => {
  await t.setup((k) => ctl(k, 'modelOn', 'off'));
  await t.expectText('Home says the Planner cannot read new requests', /I can’t read new requests until an AI model is connected/);
  await t.expectCount('The Visor bot is in its sorry pose', 'main .welcome .face.fs-sorry', 1);
  await t.expectCount('There is no Planner text box', 'main [data-ask]', 0);
  await t.expectText('Needs you still shows', /Needs you/);
  await t.click('main [data-act="setGo"][data-arg="model"]', 'Connect a model');
  await t.expect('Settings opens on AI model', t.page.evaluate(() => location.hash), /settings/);
  await t.expectText('The AI model panel offers to connect one', /Connect a model/);
}, [1280, 390]);

add('DOWN', 'Jira stops answering: the Planner says so, then Jira works again', async (t) => {
  await t.setup((k) => ctl(k, 'Jira stops answering'));
  await t.ask(WEEKLY_SUMMARY);
  await t.expectText('The Planner says Jira is not answering', /Jira isn’t answering right now, so I can’t check that/, 'main .thread');
  await t.expectCount('No set-up card is offered while Jira is down', 'main .thread [data-act="turnOn"]', 0);
  await t.setup((k) => ctl(k, 'Jira works again'));
  await t.setup((k) => k.go('workflows'));
  await t.expect('Jira is no longer listed as not answering', t.page.innerText('main'), (v) => !/Jira isn’t answering/.test(v));
}, [1280]);

add('PREVIEW', 'Planned features shown: each planned item is tagged', async (t) => {
  await t.setup((k) => ctl(k, 'preview', 'on'));
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('The access review is listed and tagged Planned', /Quarterly access review[\s\S]{0,300}PLANNED/i);
  await t.click(S.row('access'), 'Open Quarterly access review');
  await t.expectText('Two Approvers in turn, tagged Planned', /First Bob, with Siti as backup\. Then Alice, with Arun as backup\.\s*PLANNED/i);
  await t.menu('software', 'Open Watchlist');
  await t.expectText('Planned sources are tagged', /Security advisories\s+Planned/i);
}, [1280]);

/* The shell (ADR 0043, step 1): the pinned line, the side panel, More details with Back to the chat, and the rail returning to the chat. */
const issuesRow = 'main .thread [data-act="workflow"][data-arg="issues"]';
add('SHELL-pinned', 'The pinned Needs you line shows after the first message, with Open and N more', async (t) => {
  await t.expectCount('No pinned line before the first message', 'main .pinned', 0);
  await t.ask(CHECK_WORKFLOWS);
  await t.expectText('The pinned line names the most urgent item', /Morning new-ticket check stopped/, 'main .pinned');
  await t.expectText('It offers Open and the rest', /Open[\s\S]*4 more/, 'main .pinned');
  await t.click('main .pinned [data-act="go"][data-arg="workflows"]', '4 more');
  await t.expectText('N more opens the Needs you list on Workflows', /Needs you\s+5[\s\S]*Do now[\s\S]*Set up/);
}, [1280, 390]);

add('SHELL-panel', 'A card in the chat opens its workflow in a side panel, or full screen on a phone, and Close puts it back', async (t) => {
  await t.ask(CHECK_WORKFLOWS);
  await t.click(issuesRow, 'Open Morning new-ticket check from the card');
  await t.expectCount('The side panel is open', '#sidepanel', 1);
  await t.expectText('It shows the last and next run', /Last run[\s\S]*Next run/, '#sidepanel');
  const box = await t.page.evaluate(() => { const r = document.querySelector('#sidepanel').getBoundingClientRect(); return { w: Math.round(r.width), vw: innerWidth, thread: !!document.querySelector('.thread') && document.querySelector('.thread').getBoundingClientRect().width > 0 }; });
  if (t.kit.width > 900) await t.expect('The chat stays beside the panel', box, (b) => b.thread && b.w < b.vw / 2);
  else await t.expect('On a phone the panel fills the screen', box, (b) => b.w === b.vw);
  await t.expect('The card hides its own Open button while the panel shows it', t.page.locator('main .thread .btn[data-act="workflow"][data-arg="issues"]').count(), 0);
  await t.click('#sidepanel [data-act="panelClose"]', 'Close');
  await t.expectCount('The panel is gone', '#sidepanel', 0);
}, [1280, 390]);

add('SHELL-more', 'More details gives a full page with Back to the chat, and the panel is still there on return', async (t) => {
  await t.ask('Why did Morning new-ticket check stop?');
  await t.click('main .thread [data-act="run"][data-arg="issues"]', 'See the run from the card');
  await t.expectText('The panel shows the three answers and Retry', /What happened[\s\S]*What was affected[\s\S]*Safe to retry[\s\S]*Retry the run/, '#sidepanel');
  await t.click('#sidepanel [data-act="panelPage"]', 'More details');
  await t.expectText('A full page opens with Back to the chat', /Back to the chat/);
  await t.expectCount('The chat is not shown on a full page', '.thread', 0);
  await t.click('main .back', 'Back to the chat');
  await t.expectCount('The panel is still there', '#sidepanel', 1);
}, [1280, 390], { changed: 'ADR 0043 step 3: the third answer is named Safe to retry. Was /…Can it be fixed safely…Retry the run/.' });

add('SHELL-rail', 'The rail returns to the chat as it was, scroll position included', async (t) => {
  await t.ask('What can you do?');
  await t.ask(CHECK_WORKFLOWS);
  await t.setup((k) => k.page.evaluate(() => { document.querySelector('.chatscroll').scrollTop = 150; }));
  const before = await t.page.evaluate(() => document.querySelector('.chatscroll').scrollTop);
  await t.expect('The chat was scrolled', before, (v) => v > 0);
  await t.menu('workflows', 'Open Workflows');
  await t.expectCount('Workflows is a full page with no chat', '.thread', 0);
  await t.menu('home', 'Back to Chat');
  await t.expectText('The conversation is back', /Check my workflows/, '.thread');
  await t.expect('The scroll position is the same', t.page.evaluate(() => document.querySelector('.chatscroll').scrollTop), before);
}, [1280, 390]);

/* The Planner's answers (ADR 0043, step 2): every part of a request is marked, one question at a time, and a time is never guessed. */
const STALE = 'Every Friday at 9 AM, find Jira tickets that haven\'t been updated for 10 days and prepare a summary.';
const CROSS = 'Every Friday at 9 AM, find the Jira tickets and prepare a summary, and colour them by team';
add('ANS-cross', 'A clause the Planner can’t read gets a cross that quotes it, and the button sets up the part it can', async (t) => {
  await t.ask(CROSS, 'a request with “colour them by team”, which no rule reads');
  await t.expectText('The dropped clause is quoted with a cross', /“colour them by team”\s*I didn’t follow this part\./, 'main .thread .part[data-mark="no"]');
  await t.expectText('The reply says it can’t do every part', /I can’t do every part of it/, 'main .thread');
  await t.expectText('The button sets up the part it can', /Set up the part I can/, 'main .thread .pcard-f');
  await t.click(S.answer('tickets:open'), 'Choose Open tickets', { decision: true });
  await t.click(S.answer('project:MOCK'), 'Choose MOCK', { decision: true });
  await t.expect('Nothing is unclear never shows while a part has a cross', t.page.innerText('main .thread'), (v) => !/Nothing is unclear/.test(v));
  await t.expectText('The footer says the crossed part is left out', /The part with a cross is left out\./, 'main .thread .pcard-f');
  await t.click(S.turnOn, 'Set up the part I can', { decision: true });
  await t.expectText('The part it can is on', /is on\./);
}, [1280, 390], { changed: 'Fix pass S3: “haven’t been updated for 10 days” now gets the honest “I can’t see when a ticket was last updated yet” (ANS-stale), so the generic cross is proved with a clause no rule reads.' });

add('ANS-left-out', 'After “Set up the part I can”, the card and the workflow’s page still say what was left out', async (t) => {
  await t.ask(CROSS);
  await t.click(S.answer('tickets:open'), 'Choose Open tickets', { decision: true });
  await t.click(S.answer('project:MOCK'), 'Choose MOCK', { decision: true });
  await t.click(S.turnOn, 'Set up the part I can', { decision: true });
  await t.expectText('The done card says what was left out', /is on\.\s*Left out: “colour them by team”\./, lastCard);
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('conf'), 'Open the new workflow');
  await t.expectText('So does its page', /Left out: “colour them by team”\. It was set up without that part\./);
}, [1280]);

add('ANS-verbs', 'A clause of verbs and little words, such as “let me know”, still gets a cross, and never “Nothing is unclear”', async (t) => {
  await t.ask('every Friday at 5pm, sum up the tickets we closed this week in MOCK and let me know');
  await t.expectText('“let me know” is quoted with a cross', /“let me know”\s*I didn’t follow this part\./, `${lastCard} .part[data-mark="no"]`);
  await t.expect('Nothing is unclear doesn’t show', t.page.innerText(lastCard), (v) => !/Nothing is unclear/.test(v));
  await t.ask('every Friday at 5pm, sum up the tickets we closed this week in MOCK, and then check it');
  await t.expectText('“check it” is quoted with a cross', /“check it”\s*I didn’t follow this part\./, `${lastCard} .part[data-mark="no"]`);
  await t.ask('every Friday at 5pm, sum up the tickets we closed this week in MOCK, and for them');
  await t.expectText('A clause of little words alone is quoted too', /“for them”\s*I didn’t follow this part\./, `${lastCard} .part[data-mark="no"]`);
}, [1280]);

add('ANS-whole-clause', 'A cross quotes the whole clause, not one word of it', async (t) => {
  await t.ask('watch Kubernetes but only the major releases');
  await t.expectText('The whole clause is quoted', /“only the major releases”\s*I didn’t follow this part\./, `${lastCard} .part[data-mark="no"]`);
}, [1280]);

add('ANS-stale', 'Every wording of “not updated for a while” gets the honest can’t, never a silent drop', async (t) => {
  for (const q of ['every Friday, list the tickets that haven\'t been updated for 10 days', 'every Friday, list the tickets that have not been updated for 10 days', 'every Friday, list the tickets with no update since Monday']) {
    await t.ask(q);
    await t.expect(`“${q}” says what it can’t see`, lastSay(t), /I can’t see when a ticket was last updated yet/);
  }
}, [1280]);

add('ANS-none-hers', 'A request with no part in her own words gets no set-up card of guesses', async (t) => {
  await t.ask('which software is behind, then raise tickets for them');
  await t.expectCount('No set-up card', `${lastCard} [data-act="turnOn"]`, 0);
  await t.expectText('Each clause is marked: the question to ask on its own, the rest not followed', /“which software is behind”\s*Ask this on its own, and I’ll answer it\.[\s\S]*“raise tickets”\s*I didn’t follow this part\./, lastCard);
}, [1280], { changed: 'Second fix pass F3: in a clause a rule read (“tickets”), the cross quotes only the unread run, so “raise tickets” instead of “raise tickets for them”.' });

add('ANS-leftover-everywhere', 'A part answer and an edit card mark the clauses they didn’t read too', async (t) => {
  await t.ask('every Friday at 5pm, sum up the closed tickets in MOCK, excluding bugs, and tag Bob');
  await t.expect('The part answer says what it can’t see', lastSay(t), /I can’t tell a ticket’s type yet/);
  await t.expectText('“tag Bob” is marked', /“tag Bob”\s*I didn’t follow this part\./, lastCard);
  await t.ask('is LangGraph up to date? set it to check daily');
  await t.expectText('The edit card keeps the question, to ask on its own', /“is LangGraph up to date”\s*Ask this on its own, and I’ll answer it\.[\s\S]*Before\s+Every Monday at 9:00\s+After\s+Every day at 9:00/, lastCard);
  await t.expectCount('A question asked alongside doesn’t hold Save change', `${lastCard} [data-act="editSave"]:not([disabled])`, 1);
}, [1280], { changed: 'Second fix pass, decision (a): only a cross on the change itself, two days or two times, holds Save change. A question asked alongside keeps its cross. Was: Save change waits while any part has a cross.' });

/* Second fix pass. */
const EMAIL_TEAM = 'every Friday, sum up the closed tickets and email the summary to the team';
add('ANS-cant-clause', 'A can’t answer never crosses the clause it answered', async (t) => {
  await t.ask(EMAIL_TEAM);
  await t.expect('It says it can’t send email', lastSay(t), /I can’t send email/);
  await t.expectCount('No cross for the email clause it answered', `${lastCard} .part[data-mark="no"]`, 0);
}, [1280]);

const crosses = (t) => t.page.$$eval(`${lastCard} .part[data-mark="no"]`, (xs) => xs.map((x) => x.innerText.replace(/^Can’t do:\s*/, '').replace(/\s+/g, ' ')).join(' | '));
add('ANS-cant-runs', 'A can’t answer reads only its can’t phrase, so the rest of that clause is still marked', async (t) => {
  await t.ask('every Friday, sum up the closed tickets and email the summary in French to the team');
  await t.expect('“in French” is marked', crosses(t), /^“in French” I didn’t follow this part\.$/);
  await t.ask('every Friday sum up the closed tickets in MOCK and email it to Bob with a chart');
  await t.expect('“with a chart” is marked', crosses(t), /^“with a chart” I didn’t follow this part\.$/);
  await t.ask('watch Grafana every day at 8am on Slack too');
  await t.expect('The time the watchlist doesn’t keep is marked', crosses(t), /^“every day at 8am” The Software watchlist checks all your software together, every Monday at 9:00\./);
}, [1280]);

add('ANS-phrase-runs', 'A summary’s describing words are read, and a quote keeps its object and the phrase it names', async (t) => {
  await t.ask('every Friday prepare a detailed summary of the closed tickets in MOCK');
  await t.expectCount('“a detailed summary” is read, so nothing is crossed', `${lastCard} .part[data-mark="no"]`, 0);
  await t.ask('every Friday at 9am, list the closed tickets in MOCK, group them by assignee and highlight blockers');
  await t.expect('“group them” keeps its object', crosses(t), /“group them” I didn’t follow this part\./);
  await t.ask('watch Kubernetes and ping Bob when a new version is out');
  await t.expect('“ping Bob when a new version” runs through “a”', crosses(t), /“ping Bob when a new version” I didn’t follow this part\./);
}, [1280]);

add('ANS-cant-alternative', 'The alternative to an email request sets up cleanly, with the email clause gone', async (t) => {
  await t.setup((k) => k.ask(EMAIL_TEAM));
  await t.click(`${lastCard} [data-act="instead"]`, 'Set that up', { reply: true, decision: true });
  await t.expectCount('A set-up card', `${lastCard} [data-act="turnOn"]`, 1);
  await t.expectCount('With no cross', `${lastCard} .part[data-mark="no"]`, 0);
}, [1280]);

add('ANS-ticked-runs', 'In a clause a rule read, a cross quotes only the unread words, and the gaps are read', async (t) => {
  await t.ask('every Friday at 5pm sum up the closed tickets in MOCK with a chart');
  await t.expect('Only “with a chart” is crossed', t.page.$$eval(`${lastCard} .part[data-mark="no"] .pk`, (xs) => xs.map((x) => x.innerText.replace(/^Can’t do:\s*/, '')).join(' | ')), '“with a chart”');
  for (const q of ['give me a short summary of the closed tickets in MOCK every Monday at 9am', 'every Monday at 9am sum up the closed tickets in MOCK, then file it as a Jira ticket', 'watch Grafana and tell me when there is a new version']) {
    await t.ask(q);
    await t.expectCount(`“${q}” has no cross`, `${lastCard} .part[data-mark="no"]`, 0);
  }
}, [1280]);

add('ANS-narrow-cards', 'Beside the panel, a narrow chat gives the cards two-column rows, and a chip stays on one line', async (t) => {
  await t.ask(WEEKLY_SUMMARY);
  await t.expectCount('The panel is open', '#sidepanel', 1);
  const cols = () => t.page.$$eval(`${lastCard} .part`, (ps) => ps.map((p) => getComputedStyle(p).gridTemplateColumns.split(' ').length));
  await t.expect('Every part row has two columns', cols(), (v) => v.length > 0 && v.every((n) => n === 2));
  await t.expect('“Tickets closed this week” is one line', t.page.$eval(`${lastCard} [data-part="tickets"] .schip`, (c) => c.getBoundingClientRect().height), (h) => h < 40);
}, [901, 1024]);

add('ANS-clash-day', 'Two days in a set-up request ask which one, and an edit card takes focus at its heading', async (t) => {
  await t.ask('every Monday and Friday at 9am list open tickets in MOCK');
  await t.expectText('The day is a question between the two', /Monday or Friday\?/, S.asks);
  await t.ask('Make the morning new-ticket check run on Mondays only');
  await t.expect('Focus is on the edit card’s heading', focused(t.page), /^h3#card-h-\d+$/);
}, [1280]);

add('ANS-clash-time', 'Two times in a set-up request ask which one, never the first picked', async (t) => {
  await t.ask('every Friday at 9am and 5pm list open tickets in MOCK');
  await t.expectText('The time is a question between the two', /9:00 or 17:00\?/, S.asks);
  await t.expect('No time is ticked', t.page.innerText(`${lastCard} .parts`), (v) => !/Every Friday at \d{1,2}:\d{2}, Singapore time/.test(v));
  await t.click(S.answer('time:17:00'), 'Choose 17:00', { decision: true });
  await t.expectText('Then it runs at the time chosen', /Every Friday at 17:00, Singapore time/, `${lastCard} .parts`);
}, [1280]);

add('ANS-testctl', 'The test controls never cover the product, scrolled or not, chatting or not', async (t) => {
  const covered = () => t.page.evaluate(() => {
    const b = document.querySelector('.testctl-toggle').getBoundingClientRect();
    /* Text scrolled out of the chat column is clipped by it, so only its visible part counts. */
    const seen = (el) => { const r = el.getBoundingClientRect(); const sc = el.closest('.chatscroll'); if (!sc) return r; const c = sc.getBoundingClientRect(); return { left: r.left, right: r.right, top: Math.max(r.top, c.top), bottom: Math.min(r.bottom, c.bottom) }; };
    return [...document.querySelectorAll('main *')].filter((el) => !el.children.length && el.textContent.trim() && el.getClientRects().length).some((el) => { const r = seen(el); return r.top < r.bottom && r.left < b.right && r.right > b.left && r.top < b.bottom && r.bottom > b.top; });
  });
  for (const y of [0, 500, 99999]) {
    await t.setup((k) => k.page.evaluate((v) => window.scrollTo(0, v), y));
    await t.expect(`Home, scrolled to ${y}: nothing under the toggle`, covered(), false);
  }
  await t.ask(WEEKLY_SUMMARY);
  for (const y of [0, 300, 99999]) {
    await t.setup((k) => k.page.evaluate((v) => { const sc = document.querySelector('.chatscroll'); if (sc) sc.scrollTop = v; }, y));
    await t.expect(`Chatting, scrolled to ${y}: nothing under the toggle`, covered(), false);
  }
}, [1280, 900, 390]);

/* The edit card's fix pass: every clause accounted for, a name never read as a schedule, questions never taken as changes. */
add('ANS-edit-days', 'Two days for one schedule get a cross, and Save change waits', async (t) => {
  await t.ask('make the morning new-ticket check run on Mondays and Thursdays');
  await t.expectText('The days are quoted with the reason', /“Mondays and Thursdays”\s*I can only set one day\./, lastCard);
  await t.expectCount('Save change waits', `${lastCard} [data-act="editSave"][disabled]`, 1);
}, [1280]);

add('ANS-name-words', 'A schedule word in a workflow’s name is neither a schedule nor a command', async (t) => {
  await t.ask('make the weekly summary run at 10am');
  await t.expectText('Only the time changes, and the day stays', /Before\s+Every Friday at 16:00\s+After\s+Every Friday at 10:00/, lastCard);
  await t.ask('what went wrong with the weekly summary?');
  await t.expect('A question about the weekly summary gets the troubleshooter', lastSay(t), /^Weekly closed-ticket summary stopped\. Here’s what the AI troubleshooter found\.$/);
  await t.expectCount('No set-up card', `${lastCard} [data-act="turnOn"]`, 0);
  await t.ask('what went wrong with the weekly summary? pause it');
  await t.expect('A real change word outside the name still takes the command path', lastSay(t), /From the chat I can only change when Weekly closed-ticket summary runs\./);
}, [1280]);

add('ANS-questions', 'Asking when a workflow runs gets its state and next run, never “I can only change”', async (t) => {
  await t.ask('when does the software check run next?');
  await t.expect('The software check’s next run', lastSay(t), /^Keep our software up to date is waiting for a yes\. Its next run is Mon 2 Nov, 9:00\.$/);
  await t.ask('when is the next run of the morning check');
  await t.expect('The morning check’s next run', lastSay(t), /^Morning new-ticket check stopped\. Its next run is Wed 28 Oct, 8:00\.$/);
  await t.ask('is the morning check running?');
  await t.expect('Is it running: its state', lastSay(t), /^Morning new-ticket check stopped\./);
  await t.ask('when does the morning check run? make it run daily');
  await t.expectText('A question with a change in it gets the edit card', /Before\s+Every weekday at 8:00\s+After\s+Every day at 8:00/, lastCard);
}, [1280]);

add('ANS-edit-missing', 'A workflow that doesn’t exist is named, and a change it can’t make keeps the question asked with it', async (t) => {
  await t.setup((k) => k.setDay('one'));
  await t.ask('make the morning check run on Mondays only');
  await t.expect('Day one: no such workflow', lastSay(t), /^You don’t have a workflow called “morning check”\.$/);
  await t.expectCount('No set-up card', `${lastCard} [data-act="turnOn"]`, 0);
  await t.setup((k) => k.setDay('week'));
  await t.ask('how are my workflows? turn the weekly one off');
  await t.expect('Turning it off is on its page', lastSay(t), /From the chat I can only change when Weekly closed-ticket summary runs\./);
  await t.expectText('The question is kept, to ask on its own', /“how are my workflows”\s*Ask this on its own, and I’ll answer it\./, lastCard);
}, [1280]);

add('ANS-edit-after', 'After Save change: the watchlist says who owns it, a paused workflow says so, and a later change elsewhere is named', async (t) => {
  await t.ask('Make the software watchlist check run every day at 7am');
  await t.click(`${lastCard} [data-act="editSave"]`, 'Save change', { decision: true });
  await t.expect('Saving the watchlist says what the page says', lastSay(t), /^Saved\. Next run Wed 28 Oct, 7:00\. You now own this schedule, so you can’t approve its checks\.$/);
  await t.expectText('The note is in the past tense now', /This changed when all \d+ software on the watchlist are checked, and made you the owner of this schedule\./, lastCard);
  await t.setup(async (k) => { await k.go('workflows'); await k.page.click(S.row('issues')); await k.settle(); await k.page.click('main [data-act="pause"][data-arg="issues"]'); await k.settle(); await k.go('home'); });
  await t.ask('Make the morning new-ticket check run on Mondays only');
  await t.click(`${lastCard} [data-act="editSave"]`, 'Save change', { decision: true });
  await t.expect('A paused workflow says it is paused', lastSay(t), /^Saved\. Morning new-ticket check is paused, so it won’t run until you resume it\.$/);
  await t.setup(async (k) => { await k.go('workflows'); await k.page.click(S.row('issues')); await k.settle(); await k.page.click('main [data-act="editSched"][data-arg="issues"]'); await k.settle(); await k.page.fill('#sf-time', '10:30'); await k.page.click('[data-act="saveSched"]'); await k.settle(); await k.go('home'); });
  await t.expect('A later change on its page is named, not mixed in', lastSay(t), /^Saved as version 2\. Changed again since, on its page\.$/);
  await t.expectCount('Undo is gone', `${lastCard} [data-act="editUndo"]`, 0);
}, [1280]);

add('ANS-asks', 'A bare hour is asked, “make it daily” after a draft offers the draft, and three more questions are answered from state', async (t) => {
  await t.ask('make the morning check run at 9');
  await t.expectText('“at 9” is asked as morning or evening', /At 9:00 or 21:00\?/, lastCard);
  await t.click(`${lastCard} [data-act="editSet"][data-arg="time:09:00"]`, 'Choose 9:00', { decision: true });
  await t.expectText('Then the change is ready', /After\s+Every weekday at 9:00/, lastCard);
  await t.ask(WEEKLY_SUMMARY);
  await t.ask('make it daily');
  await t.expectText('The draft above is one of the choices', /Friday closed ticket summary, the draft above/, lastCard);
  await t.ask('do I have approvals waiting');
  await t.expect('Approvals waiting', lastSay(t), /^1 approval is waiting for your yes\.$/);
  await t.ask('which version of FastAPI do we run?');
  await t.expect('The version we run', lastSay(t), /^FastAPI is behind\. You run 0\.118\.0 and the newest is 0\.120\.1\.$/);
}, [1280]);

add('ANS-one-question', 'With nothing said about when, the card asks how often, then the day, then the time, one at a time', async (t) => {
  await t.ask('sum up the tickets we closed in project MOCK', 'a request with no schedule');
  await t.expectCount('One question shows', S.asks, 1);
  await t.expectText('It asks how often first', /How often should it run\?/, S.asks);
  await t.click(S.answer('freq:week'), 'Every week', { decision: true });
  await t.expectCount('Still one question', S.asks, 1);
  await t.expectText('Then the day', /Which day should it run\?/, S.asks);
  await t.click(S.answer('day:Friday'), 'Friday', { decision: true });
  await t.expectText('Then the time', /What time should it run\?/, S.asks);
  await t.click(S.answer('time:09:00'), 'Choose 9:00', { decision: true });
  await t.expectCount('No question is left', S.asks, 0);
  await t.expectText('The card reads back the schedule it was given', /Every Friday at 9:00, Singapore time/, 'main .thread .parts');
}, [1280, 390]);

add('ANS-no-time', 'A request that names a day but no time is asked for the time, never given one', async (t) => {
  await t.ask(WEEKLY_SUMMARY);
  await t.expectText('The card asks what time', /What time should it run\?/, S.asks);
  await t.expect('No time is filled in', t.page.innerText('main .thread .parts'), (v) => !/\d{1,2}:\d{2}, Singapore time/.test(v));
  await t.expectCount('Turn it on waits for the time', '[data-act="turnOn"][disabled]', 1);
}, [1280]);

add('ANS-watch-parts', 'Watching software marks each part, and a time the watchlist doesn’t keep gets a cross', async (t) => {
  await t.ask('watch Kubernetes every Monday at 9am and create a Jira ticket');
  await t.expectCount('No part has a cross', 'main .thread li.cmsg:last-child .part[data-mark="no"]', 0);
  await t.expectText('The schedule and the ticket are her words', /Checked\s+Every Monday at 9:00\s+From your words[\s\S]*Then\s+An upgrade ticket in Jira for each newer version\s+From your words/, 'main .thread li.cmsg:last-child');
  await t.expectCount('One question at a time: the project first, not the version', 'main .thread li.cmsg:last-child .part[data-mark="ask"]', 1);
  await t.ask('watch Grafana every day at 8am');
  await t.expectText('Its own time gets a cross with the reason', /“every day at 8am”\s*The Software watchlist checks all your software together, every Monday at 9:00\./, 'main .thread li.cmsg:last-child');
}, [1280, 390]);

/* Changing a workflow by asking (ADR 0043): the edit card changes the schedule, as a new version with Undo. */
const lastCard = 'main .thread li.cmsg:last-child';
add('ANS-edit-save', 'Change a schedule by asking: Save change publishes version 2, the page lists it, and Undo goes back', async (t) => {
  await t.ask('Make the morning new-ticket check run on Mondays only');
  await t.expectText('The card shows only what changes, before and after', /When it runs\s+Before\s+Every weekday at 8:00\s+After\s+Every Monday at 8:00/, lastCard);
  await t.expectCount('No new set-up card', `${lastCard} [data-act="turnOn"]`, 0);
  await t.click(`${lastCard} [data-act="editSave"]`, 'Save change', { decision: true });
  await t.expectText('It is saved as version 2', /Saved as version 2\. Next run Mon 2 Nov, 8:00\./, lastCard);
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.expectText('The page runs on the new schedule', /Every Monday at 8:00, Singapore time/);
  await t.expectText('The page lists version 2', /Versions\s+Version 2\s+Today, 9:10\. Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00\. This is the version running now\.\s+Version 1/);
  await t.menu('home', 'Back to Chat');
  await t.click(`${lastCard} [data-act="editUndo"]`, 'Undo', { decision: true });
  await t.expectText('Undo publishes the version before again', /Undone, as version 3\. Morning new-ticket check runs every weekday at 8:00 now\./, lastCard);
  await t.setup(async (k) => { await k.go('workflows'); await k.page.click(S.row('issues')); await k.settle(); });
  await t.expectText('The page lists the undo as version 3', /Version 3\s+Today, 9:10\. Alice undid version 2, so it runs every weekday at 8:00 again\./);
}, [1280, 390]);

add('ANS-edit-never', 'The review’s “every day instead of every Monday” gets an edit card, and Never mind changes nothing', async (t) => {
  await t.ask('Run the software check every day instead of every Monday');
  await t.expectText('Before and after, for every software on the watchlist', /Before\s+Every Monday at 9:00\s+After\s+Every day at 9:00[\s\S]*all 14 software on the watchlist/, lastCard);
  await t.click(`${lastCard} [data-act="editKeep"]`, 'Never mind', { decision: true });
  await t.expectText('Nothing changed', /No problem\. Nothing changed\./, lastCard);
  await t.menu('software', 'Open Watchlist');
  await t.expectText('The watchlist still runs every Monday', /Every Monday at 9:00, Singapore time/);
  await t.expect('No version was published', t.page.innerText('main'), (v) => !/Version 2/.test(v));
}, [1280]);

add('ANS-edit-honest', 'A change the card can’t make gets an honest answer, and a check that doesn’t exist is named', async (t) => {
  await t.ask('Make the React check run on Mondays only');
  await t.expectText('There is no React check, and React isn’t watched', /You don’t have a React check\. React isn’t on the Software watchlist, which checks software every Monday\./, lastCard);
  await t.expectCount('No set-up card for it', `${lastCard} [data-act="turnOn"]`, 0);
  await t.expectCount('It offers to watch React', `${lastCard} [data-act="say"][data-arg="Keep track of the React version"]`, 1);
  await t.ask('rename the morning check to Daily tickets');
  await t.expectText('Only the schedule changes from the chat', /From the chat I can only change when Morning new-ticket check runs\./, lastCard);
  await t.expectCount('It offers the workflow itself, with no edit card', `${lastCard} :is([data-act="workflow"][data-arg="issues"], [data-act="editSave"])`, 1);
}, [1280]);

/* Status questions in any wording (ADR 0043), failing closed: a text with a change word gets the command path. */
const lastSay = (t) => t.page.locator('main .thread [data-say]').last().innerText();
add('ANS-status', 'Questions in other words get answers from platform state', async (t) => {
  for (const q of ['what needs my attention today?', 'anything for me?', 'what’s waiting on me']) {
    await t.ask(q);
    await t.expect(`“${q}” gets what needs her`, lastSay(t), /^5 things need you\.$/);
  }
  await t.ask('is LangGraph up to date?');
  await t.expect('“is LangGraph up to date?” gets its versions', lastSay(t), /^LangGraph is behind\. You run 1\.2\.14 and the newest is 1\.2\.17\.$/);
  await t.ask('which software is behind?');
  await t.expect('“which software is behind?” names them, with the watchlist’s own count', lastSay(t), /^3 have a newer version: Log4j core, LangGraph and FastAPI\.$/);
  await t.ask('how are my workflows doing');
  await t.expect('“how are my workflows doing” sums them up', lastSay(t), /^You have 3 workflows\. 2 stopped and 1 is waiting for a yes\.$/);
}, [1280, 390]);

add('ANS-status-commands', 'A question with a change word in it is a command, never a status answer', async (t) => {
  const STATUS = /things need you|Nothing needs you|You have \d+ workflows|is behind|is up to date|have a newer version/;
  await t.ask('can you make the React check daily?');
  await t.expect('“can you make the React check daily?” goes to the command path', lastSay(t), (v) => !STATUS.test(v) && /You don’t have a React check/.test(v));
  await t.ask('what needs my attention? pause the morning check');
  await t.expect('A status question with a pause in it goes to the command path', lastSay(t), (v) => !STATUS.test(v) && /From the chat I can only change when Morning new-ticket check runs/.test(v));
  await t.ask('is LangGraph up to date? if not, watch it every day');
  await t.expect('A software question with a watch in it goes to the command path', lastSay(t), (v) => !STATUS.test(v));
  await t.ask('how are my workflows doing? make the morning check run at 10am');
  await t.expectText('A workflows question with a change in it gets the edit card', /Before\s+Every weekday at 8:00\s+After\s+Every weekday at 10:00/, lastCard);
}, [1280]);

/* Live cards (ADR 0043): every card in the chat reads current state, so a change made anywhere shows in older answers. */
add('ANS-live', 'An older answer reads current state: a pause in the panel and an approval on another page show in it', async (t) => {
  await t.ask(CHECK_WORKFLOWS);
  await t.expectText('The answer starts with two stopped and one waiting', /You have 3 workflows\. 2 stopped and 1 is waiting for a yes\./, 'main .thread');
  await t.click(issuesRow, 'Open Morning new-ticket check from the card');
  await t.click('#sidepanel [data-act="pause"]', 'Pause it in the panel', { decision: true });
  await t.click('#sidepanel [data-act="panelClose"]', 'Close');
  await t.expectText('The older answer says it is paused', /You have 3 workflows\. 1 stopped, 1 is waiting for a yes and 1 paused\./, 'main .thread');
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.review, 'Review and decide');
  await t.click(S.approve, 'Approve', approvedOpts);
  await t.menu('home', 'Back to Chat');
  await t.expectText('The older answer no longer waits for a yes', /You have 3 workflows\. 1 stopped, 1 is on and 1 paused\./, 'main .thread');
}, [1280]);

add('ANS-live-done', 'A workflow turned on in the chat, then paused on its page, reads as paused back in the chat', async (t) => {
  await t.setup(turnOnWeekly);
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('conf'), 'Open Friday closed ticket summary');
  await t.click('main [data-act="pause"][data-arg="conf"]', 'Pause', { decision: true });
  await t.menu('home', 'Back to Chat');
  await t.expectText('The card and its sentence say it is paused', /Friday closed ticket summary is paused\.[\s\S]*Friday closed ticket summary is paused\./, 'main .thread');
}, [1280]);

/* The panel opens by itself while the Planner builds (ADR 0043), wider than 900 px only, and a flow shows once. */
add('ANS-panel', 'While the Planner builds, the panel opens by itself with the steps going in, but never on a phone', async (t) => {
  await t.ask(WEEKLY_SUMMARY);
  if (t.kit.width > 900) {
    await t.expectCount('The side panel opened by itself', '#sidepanel', 1);
    await t.setup((k) => k.page.waitForFunction(() => document.querySelectorAll('#sidepanel .steps li').length >= 3));
    await t.expectText('It shows the new workflow’s steps, as a draft', /Draft[\s\S]*Find the tickets closed[\s\S]*Write a short summary[\s\S]*Create one ticket/, '#sidepanel');
    await t.expect('The chat keeps focus on the card', focused(t.page), (v) => !/^button\[panelClose\]$/.test(v));
    await t.expectCount('The card hides its own steps while the panel shows them', 'main .thread details.how:not([hidden])', 0);
    await t.click('#sidepanel [data-act="panelClose"]', 'Close');
    await t.expectCount('The card’s steps come back', 'main .thread details.how:not([hidden])', 1);
  } else {
    await t.expectCount('At 900 px or less the panel doesn’t open by itself', '#sidepanel', 0);
    await t.expectCount('The card keeps its own steps', 'main .thread details.how:not([hidden])', 1);
  }
}, [1280, 880, 390], { changed: 'The panel opens by itself only wider than 900 px, the same breakpoint as the rail’s top bar (fix pass S9), so 880 is checked too.' });

add('ANS-panel-focus', 'Focus stays on the card’s heading while the panel opens by itself and the steps go in', async (t) => {
  await t.ask(WEEKLY_SUMMARY);
  await t.setup((k) => k.page.waitForFunction(() => document.querySelectorAll('#sidepanel .steps li').length >= 3));
  await t.expect('Focus is on the card heading, not on Rename', focused(t.page), /^h3#card-h-\d+$/);
}, [1440, 1280]);

add('ANS-scroll-390', 'On a phone, answering the card’s questions and saving a change never scrolls the app out of place', async (t) => {
  const appTop = () => t.page.evaluate(() => [document.getElementById('app').scrollTop, window.scrollY, Math.round(document.querySelector('.hdr').getBoundingClientRect().top)]);
  await t.ask(WEEKLY_SUMMARY);
  await t.click(S.answer('time:17:00'), 'Choose 17:00', { decision: true });
  await t.click(S.answer('project:MOCK'), 'Choose MOCK', { decision: true });
  await t.expect('The app has not scrolled, and the header is in place', appTop(), (v) => v.every((x) => x === 0));
  await t.ask('Make the morning new-ticket check run on Mondays only');
  await t.click(`${lastCard} [data-act="editSave"]`, 'Save change', { decision: true });
  await t.expect('Still in place after saving a change', appTop(), (v) => v.every((x) => x === 0));
}, [390]);

/* Keyboard only: no mouse. Tab, Shift+Tab, Enter, Space, arrows, Escape, typing. */
add('KEYS-A', 'Scenario A with the keyboard only', async (t) => {
  await t.setup(async (k) => { await k.setDay('one'); await focusTop(k); });
  await t.press('Tab', 'Tab to Skip to main content');
  await t.press('Enter', 'Skip to main content');
  await tabTo(t, '[data-ask]', 'the Planner box');
  await t.field(':focus', WEEKLY_SUMMARY, 'Type the request');
  await t.press('Enter', 'Send', { reply: true });
  await tabTo(t, '[data-act="answer"][data-arg="time:17:00"]', 'the 17:00 choice');
  await t.press('Enter', 'Choose 17:00', { decision: true });
  await t.expect('Focus moves to the next question', focused(t.page), 'button[answer=project:MOCK]');
  await t.press('Enter', 'Choose MOCK', { decision: true });
  await t.expect('Focus moves to Turn it on', focused(t.page), 'button[turnOn]');
  await t.press('Enter', 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Friday closed ticket summary is on/);
}, [1280], { changed: `The card asks ${ONE_QUESTION}, and focus moves to the next question after each answer.` });

add('KEYS-C', 'Scenario C with the keyboard only', async (t) => {
  await t.setup(async (k) => { await k.setUser('bob'); await focusTop(k); });
  await t.press('Tab', 'Tab to Skip to main content');
  await t.press('Enter', 'Skip to main content');
  await tabTo(t, '[data-act="run"][data-arg="sw"]', 'Review and decide');
  await t.press('Enter', 'Review and decide');
  await tabTo(t, '[data-act="approve"][data-arg="sw"]', 'Approve');
  await t.press('Enter', 'Approve', approvedOpts);
  await t.expectText('Bob approved and the tickets were created', /Bob approved, and the platform created the tickets/);
}, [1280]);

/* Runs and approvals (ADR 0043, step 3): a stopped run's three answers, the FLOW run line, the approval page's three
   additions, and a declined record that reads the same everywhere. */
const THREE = /What happened[\s\S]*What was affected[\s\S]*Safe to retry/;
const notFour = (v) => !/Can it be fixed safely|What to do/.test(v);
/* Each step of a run line as state>link, where the link is the one into the next step. */
const lineOf = (t, scope = 'main') => t.page.$$eval(`${scope} .line > .st`, (ls) => ls.map((l) => {
  const st = ['done', 'now', 'wait', 'fail', 'noans', 'skip', 'no', 'todo'].find((c) => l.classList.contains(c));
  const lk = l.querySelector(':scope > .lk');
  if (!lk) return st;
  const kind = ['solid', 'flow', 'stop', 'dead'].find((c) => lk.classList.contains(c)) || 'todo';
  return `${st}>${kind}${lk.classList.contains('wait') ? '-wait' : ''}${lk.classList.contains('off') ? '-off' : ''}`;
}).join(' '));
const ring = (page) => page.evaluate(() => { const cs = getComputedStyle(document.activeElement); return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (!!cs.boxShadow && cs.boxShadow !== 'none'); });
const appScroll = (t) => t.page.evaluate(() => document.getElementById('app').scrollTop);
/* The same steps as a user, not counted: Alice's weekly summary, turned on and test run, waiting for a yes. */
async function testRunWaiting(k) {
  await turnOnWeekly(k);
  await k.page.click(S.testRun);
  await k.waitText(/another Approver must decide/);
}
/* Bob opens a request from his Home and declines it, with a reason or none. Not counted. */
async function bobDeclines(k, id, why) {
  await k.setUser('bob');
  await k.go('home');
  await k.page.click(`main [data-act="run"][data-arg="${id}"]`); await k.settle();
  await k.page.click(`main [data-act="decline"][data-arg="${id}"]`); await k.settle();
  if (why) { await k.page.click(`main [data-act="declinePick"][data-arg="${why}"]`); await k.settle(); }
  await k.page.click(`main [data-act="declineYes"][data-arg="${id}"]`);
  await k.waitText(/Declined, nothing was (written|removed)/);
  await k.settle();
}

add('RUN-three', 'A stopped run answers what happened, what was affected and whether a retry is safe, the same in Needs you, the chat, the side panel and the run page', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Needs you’s first card gives the three answers', THREE, 'main article.task');
  await t.expect('Not four', t.page.innerText('main article.task'), notFour);
  await t.menu('home', 'Back to Chat');
  await t.ask('Why did Weekly closed-ticket summary stop?');
  await t.expectText('The chat card gives the three answers, then Report to support', /What happened[\s\S]*MOCK-31[\s\S]*What was affected[\s\S]*Safe to retry\s+No\.[\s\S]*Report to support/, lastCard);
  await t.expect('No fourth answer on the card', t.page.innerText(lastCard), notFour);
  await t.click(`${lastCard} [data-act="run"][data-arg="nudge"]`, 'See the run');
  await t.expectText('The side panel gives the same three, then Report to support', /What happened[\s\S]*What was affected[\s\S]*Safe to retry[\s\S]*Report to support/, '#sidepanel');
  await t.click('#sidepanel [data-act="panelPage"]', 'More details');
  await t.expectText('The run page gives the same three, then Report to support', /What happened[\s\S]*What was affected[\s\S]*Safe to retry[\s\S]*Report to support/, 'main #decision');
  await t.expect('No fourth answer on the run page', t.page.innerText('main #decision'), notFour);
}, [1280, 390]);

add('RUN-three-approver', 'An Approver sees a stopped run’s three answers with no buttons, and the note that says who can act', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('main [data-act="watch"][data-arg="issues"]', 'See the run', { until: /Stopped at Find new tickets/ });
  await t.expectText('The three answers', THREE, 'main #decision');
  await t.expectText('The note says an Operator can retry', /An Operator can retry the run\./, 'main #decision');
  await t.expectCount('No Retry button', 'main [data-act="retryIssues"]', 0);
});

add('RUN-line', 'The FLOW run line: red into the stop, amber and slow into a waiting yes, dashes into the working step, faint into skipped ones, solid once the next step is done', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.seeRun, 'See the stopped run');
  await t.expect('Solid into done steps, red dashes into the stop, plain after it', lineOf(t), 'done>solid done>stop fail>todo todo>todo todo>todo todo>todo todo');
  await t.menu('workflows', 'Back to Workflows');
  await t.click(S.review, 'Review and decide');
  await t.expect('Amber dashes into the yes that waits', lineOf(t), 'done>solid done>solid done>solid done>flow-wait wait>todo todo>todo todo');
  const march = () => t.page.$eval('main .lk.flow', (el) => [getComputedStyle(el).animationName, getComputedStyle(el).backgroundImage.includes('repeating-linear-gradient')]);
  await t.expect('The amber dashes march', march(), (v) => /^march-[xy]$/.test(v[0]) && v[1]);
  await t.setup((k) => k.page.emulateMedia({ reducedMotion: 'reduce' }));
  await t.expect('With reduced motion they hold still, and are still dashes', march(), (v) => v[0] === 'none' && v[1]);
  await t.setup((k) => k.page.emulateMedia({ reducedMotion: 'no-preference' }));
  await t.menu('workflows', 'Back to Workflows');
  await t.click(S.retry, 'Retry the run');
  await t.setup((k) => k.page.waitForFunction(() => [...document.querySelectorAll('main .line > .st')].findIndex((x) => x.classList.contains('now')) >= 2));
  await t.expect('Mid-run: dashes march into the working step, and the steps before are solid', lineOf(t), (v) => /^done>solid done>flow now>todo/.test(v));
  await t.expectText('The replay doesn’t claim Done before the line gets there', /Replaying/, 'main .runtitle');
  await t.expect('No Done pill yet', t.page.locator('main .runtitle .pill').count(), 0);
  await t.setup((k) => k.waitText(retriedText));
  await t.expect('Done: solid into done steps, faint into the skipped ones', lineOf(t), 'done>solid done>solid done>dead skip>dead skip>dead skip>solid done');
}, [1280, 861, 390]);

add('RUN-retry-from-chat', 'A retry on a run page opened from the chat keeps Back to the chat, and the chat card follows', async (t) => {
  await t.ask('Why did Morning new-ticket check stop?');
  await t.click(`${lastCard} [data-act="run"][data-arg="issues"]`, 'See the run');
  await t.click('#sidepanel [data-act="panelPage"]', 'More details');
  await t.click('main #decision [data-act="retryIssues"]', 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('Back still goes to the chat', /Back to the chat/, 'main .back');
  await t.click('main .back', 'Back to the chat');
  await t.expectText('The card says it hasn’t stopped', /Morning new-ticket check hasn’t stopped\./, lastCard);
  await t.expectCount('The card offers no retry', `${lastCard} [data-act="retryIssues"]`, 0);
  await t.expectText('The panel shows the retry done', /Done[\s\S]*Done, nothing new today/, '#sidepanel');
}, [1280, 390]);

add('RUN-line-panel', 'The side panel’s run line is the same line, small, with the same links', async (t) => {
  await t.ask('Why did Weekly closed-ticket summary stop?');
  await t.click(`${lastCard} [data-act="run"][data-arg="nudge"]`, 'See the run');
  await t.expect('Solid, then red dashes into the stop', lineOf(t, '#sidepanel'), 'done>solid done>stop fail>todo todo>todo todo>todo todo>todo todo');
  await t.expectText('The stop is named in words too', /Read closed tickets\s+Stopped here/, '#sidepanel .line');
  await t.expect('#app has not scrolled', appScroll(t), 0);
}, [1280, 901, 390]);

add('APPR-not-checked', 'The approval names what wasn’t checked, from the run and the capability registry, and the side panel trims nothing that will be written', async (t) => {
  await t.ask(CHECK_WORKFLOWS);
  await t.click('main .thread [data-act="run"][data-arg="sw"]', 'Review and decide, from the card');
  await t.expectText('The panel shows all three tickets', /Upgrade Log4j core from 2\.14\.1 to 2\.25\.2[\s\S]*Upgrade LangGraph from 1\.2\.14 to 1\.2\.17[\s\S]*Upgrade FastAPI from 0\.118\.0 to 0\.120\.1[\s\S]*exactly what will be written/, '#sidepanel');
  await t.expectText('Not checked names the software the run couldn’t read', /Not checked\s+Grafana, LangServe, PostgreSQL and Python couldn’t be read, so no ticket is proposed for them\./, '#sidepanel');
  await t.expectText('and what the platform can’t read yet, from the registry', /The platform can’t yet check registries or security advisories\./, '#sidepanel');
  await t.expect('The AI’s findings, when it was sent and why it came to her wait for the page', t.page.innerText('#sidepanel'), (v) => !/Who asked|Your part|Version checker:|asked in Teams/.test(v));
  await t.click('#sidepanel [data-act="panelPage"]', 'More details');
  await t.expectText('The full page adds them', /Not checked[\s\S]*Why[\s\S]*Version checker:[\s\S]*Who asked[\s\S]*asked in Teams[\s\S]*Your part/, 'main #decision');
  await t.setup((k) => ctl(k, 'preview', 'on'));
  await t.expect('With Planned features shown, the registry line goes, because that planned check is drawn as working', t.page.innerText('main #decision'), (v) => /Not checked/.test(v) && !/can’t yet check registries/.test(v));
}, [1280, 390]);

add('APPR-not-checked-jira', 'A ticket summary’s approval says the agents can’t see a ticket’s type, priority or owner', async (t) => {
  await t.setup(testRunWaiting);
  await t.setup((k) => k.setUser('bob'));
  await t.expectText('Not checked comes from the registry', /Not checked\s+The platform can’t yet see when a ticket was last updated, its type, component or priority, or its owner\./, 'main #decision');
});

add('APPR-ask', 'An Approver asks the requester a question: the request stays open, the answer shows on it, and nothing is decided', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click('main [data-act="askOpen"][data-arg="sw"]', 'Ask Carol a question');
  await t.expect('Focus is in the question box', focused(t.page), 'textarea#ask-sw');
  await t.click('main form[data-submit="askSend"] button[type="submit"]', 'Send with nothing typed');
  await t.expectText('An empty question is asked for', /Type your question\./, 'main .askbox');
  await t.field('#ask-sw', 'Has the FastAPI change been tested with our login service?', 'Type the question');
  await t.click('main form[data-submit="askSend"] button[type="submit"]', 'Send question', { decision: true });
  await t.expectText('The question shows on the request', /You asked Carol: Has the FastAPI change been tested with our login service\?\s+No answer yet\. The request is still waiting for a yes\./, 'main .asks');
  await t.expect('Focus is on the questions’ heading', focused(t.page), 'h2#asks-h-sw');
  await t.expectText('The request is still waiting for a yes', /Waiting for a yes/, 'main .runhead');
  await t.expectCount('Approve and Decline are still there', 'main :is([data-act="approve"], [data-act="decline"])[data-arg="sw"]', 2);
  await t.setup((k) => ctl(k, 'answerAs', 'sw:0'));
  await t.expectText('Carol’s answer shows under it', /Carol answered: Yes\. I checked it with the team on Friday\./, 'main .asks');
  await t.expectText('Still waiting for a yes', /Waiting for a yes/, 'main .runhead');
  await t.expectCount('Bob still decides', 'main [data-act="approve"][data-arg="sw"]', 1);
}, [1280, 390]);

add('APPR-answer', 'The requester finds the question in Needs you and answers it on the request, which still waits for someone else’s yes', async (t) => {
  await t.setup(async (k) => {
    await testRunWaiting(k);
    await k.setUser('bob'); await k.go('home');
    await k.page.click('main [data-act="run"][data-arg="conf"]'); await k.settle();
    await k.page.click('main [data-act="askOpen"][data-arg="conf"]'); await k.settle();
    await k.page.fill('#ask-conf', 'Should MOCK-31 be in this summary?');
    await k.page.click('main form[data-submit="askSend"] button[type="submit"]'); await k.settle();
    await k.setUser('alice');
  });
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Needs you has Bob’s question', /Bob asked you about Friday closed ticket summary[\s\S]*Should MOCK-31 be in this summary\?/, 'main section[aria-labelledby="needs-h"]');
  await t.click('main [data-act="run"][data-arg="conf"]:has-text("Answer Bob")', 'Answer Bob');
  await t.field('#ans-conf-0', 'Yes, it was closed on Friday.', 'Type the answer');
  await t.click('main form[data-submit="askAnswer"] button[type="submit"]', 'Send answer', { decision: true });
  await t.expectText('The answer shows on the request', /Bob asked you: Should MOCK-31 be in this summary\?\s+You answered: Yes, it was closed on Friday\./, 'main .asks');
  await t.expectCount('Alice still can’t approve her own test run', 'main [data-act="approve"]', 0);
  await t.menu('workflows', 'Back to Workflows');
  await t.expect('The question is gone from Needs you', t.page.innerText('main'), (v) => !/Bob asked you about/.test(v));
});

add('APPR-decline', 'Decline asks why, with quick reasons and none needed, and the reason shows with the declined record', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click('main [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.expectText('It asks why, and says it’s optional', /Why are you declining\?\s*Optional\. Carol sees it with the record\./, 'main .decide');
  await t.expect('Focus is on the first reason', focused(t.page), 'button[declinePick=Not this week]');
  await t.expectText('Nothing is declined yet', /Waiting for a yes/, 'main .runhead');
  await t.click('main [data-act="declinePick"][data-arg="Wrong version"]', 'Wrong version', { decision: true });
  await t.expectCount('The pick is marked', 'main [data-act="declinePick"][aria-pressed="true"]', 1);
  await t.click('main [data-act="declineYes"][data-arg="sw"]', 'Decline', { decision: true, until: /Declined, nothing was written/ });
  await t.expectText('The record says who declined, that nothing was written, and why', /Declined by Bob\. Nothing was written\. Reason: Wrong version\./, 'main #decision');
  await t.expectText('The run’s state is Declined', /^Declined$/, 'main .runtitle .pill');
}, [1280, 390]);

add('APPR-decline-none', 'A decline needs no reason, and then the record has none', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click('main [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.click('main [data-act="declineYes"][data-arg="sw"]', 'Decline, with no reason', { decision: true, until: /Declined, nothing was written/ });
  await t.expectText('The record', /Declined by Bob\. Nothing was written\. The tickets will be proposed again next Monday\./, 'main #decision');
  await t.expect('No reason line', t.page.innerText('main'), (v) => !/Reason:/.test(v));
});

add('APPR-panel', 'Deciding in the side panel: focus goes to the panel’s heading, #app stays put, and the card in the chat follows', async (t) => {
  await t.ask(CHECK_WORKFLOWS);
  await t.click('main .thread [data-act="run"][data-arg="sw"]', 'Review and decide, from the card');
  await t.click('#sidepanel [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.click('#sidepanel [data-act="declinePick"][data-arg="Not this week"]', 'Not this week', { decision: true });
  await t.click('#sidepanel [data-act="declineYes"][data-arg="sw"]', 'Decline', { decision: true });
  await t.expect('Focus is on the panel’s heading', focused(t.page), 'h2#sp-h');
  await t.expectText('The panel gives the record', /Declined\s+Declined by Alice\. Nothing was written\. Reason: Not this week\./, '#sidepanel');
  await t.expect('#app has not scrolled', appScroll(t), 0);
  await t.click('#sidepanel [data-act="panelClose"]', 'Close');
  await t.expectText('The card in the chat no longer waits for a yes', /Keep our software up to date\s+On/, 'main .thread');
}, [1280, 901, 390]);

add('DECLINED-sw', 'A declined upgrade check says Declined, shows no write and gives the reason: on its line, in its agents’ chat, in Teams and on the watchlist', async (t) => {
  await t.setup((k) => bobDeclines(k, 'sw', 'Wrong version'));
  await t.expect('The line: the gate declined, the write faint, the run ended', lineOf(t), (v) => /done>solid no>dead skip>solid done$/.test(v));
  await t.expectText('Its steps say so in words', /Approval gate\s+Declined[\s\S]*Create in Jira\s+Nothing written[\s\S]*Ended/, 'main .line');
  await t.expectCount('Ended is a plain dot, not a tick', 'main .line > .st:last-child .st-dot svg', 0);
  await t.click('main [data-act="runDetail"]', 'Show what each agent did');
  await t.expectText('The agents’ chat gives the record', /Declined by Bob\. Nothing was written\. Reason: Wrong version\./, 'main .run-detail');
  await t.expect('and never says it created anything', t.page.innerText('main .run-detail'), (v) => !/Created MOCK|Done\./.test(v));
  await t.click(S.teams, 'Open Teams');
  await t.expectText('Teams gives the same record', /Declined by Bob at 9:10 today\s+Nothing was written\. Reason: Wrong version\./, '.drawer');
  await t.setup(async (k) => { await k.page.keyboard.press('Escape'); await k.settle(); await k.setUser('alice'); });
  await t.menu('software', 'Open Watchlist');
  await t.click('main [data-act="swHist"][data-arg="lg"]', 'Open LangGraph’s history');
  await t.expectText('LangGraph’s history gives the record', /Found 1\.2\.17\. Declined by Bob\. Nothing was written\. Reason: Wrong version\. The tickets will be proposed again next Monday\./);
  await t.expectText('Each row’s note gives the same record', /New version\s+Declined by Bob\. Nothing was written\. Reason: Wrong version\. The tickets will be proposed again next Monday\./);
  await t.expectCount('No ticket link on the watchlist', 'main [data-act="ticket"]', 0);
});

add('DECLINED-test-run', 'A declined test run reads the same in Needs you, on its workflow page, in the chat’s side panel and in Teams', async (t) => {
  await t.setup(async (k) => { await testRunWaiting(k); await bobDeclines(k, 'conf', 'Something in it is wrong'); await k.setUser('alice'); });
  const record = 'Declined by Bob\\. Nothing was written\\. Reason: Something in it is wrong\\.';
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Needs you says Bob declined it, in the record’s words', /Bob declined your test run[\s\S]{0,80}Nothing was written\. Reason: Something in it is wrong\./, 'main section[aria-labelledby="needs-h"]');
  await t.click(S.row('conf'), 'Open the workflow');
  await t.expectText('Its recent run gives the record', new RegExp(record));
  await t.menu('home', 'Back to Chat');
  await t.ask('What needs me?');
  await t.click(`${lastCard} [data-act="run"][data-arg="conf"]`, 'See the run, from the card');
  await t.expectText('The side panel gives the record, and the state Declined', new RegExp(`Declined\\s+${record}`), '#sidepanel');
  await t.expectText('Its line says the ticket wasn’t written', /Create the ticket\s+Nothing written/, '#sidepanel');
  await t.expect('The panel shows no write', t.page.innerText('#sidepanel'), (v) => !/MOCK-33|created/i.test(v));
  await t.click(S.teams, 'Open Teams');
  await t.expectText('Teams gives the same record', /Declined by Bob at 9:10 today\s+Nothing was written\. Reason: Something in it is wrong\./, '.drawer');
  await t.setup(async (k) => { await k.page.keyboard.press('Escape'); await k.settle(); });
  await t.click('#sidepanel [data-act="panelPage"]', 'More details', { until: /Declined, nothing was written/ });
  await t.click('main [data-act="runDetail"]', 'Show what each agent did');
  await t.expectText('The run ends with what happens next, like the others', /The run ended\. Change what it does, or run the test again\./, 'main .run-detail');
});

add('KEYS-APPR', 'Ask, the decline reasons and Decline with the keyboard only, each with a visible focus', async (t) => {
  await t.setup(async (k) => { await k.setUser('bob'); await focusTop(k); });
  await t.press('Tab', 'Tab to Skip to main content');
  await t.press('Enter', 'Skip to main content');
  await tabTo(t, '[data-act="run"][data-arg="sw"]', 'Review and decide');
  await t.press('Enter', 'Review and decide');
  await tabTo(t, '[data-act="askOpen"][data-arg="sw"]', 'Ask Carol a question', 60);
  await t.expect('Ask has a visible focus', ring(t.page), true);
  await t.press('Enter', 'Open the question box');
  await t.expect('Focus is in the box', focused(t.page), 'textarea#ask-sw');
  await t.setup((k) => k.page.keyboard.type('Is the LangGraph upgrade urgent?'));
  await tabTo(t, 'form[data-submit="askSend"] button[type="submit"]', 'Send question', 5);
  await t.expect('Send question has a visible focus', ring(t.page), true);
  await t.press('Enter', 'Send question', { decision: true });
  await t.expectText('The question is on the request', /You asked Carol: Is the LangGraph upgrade urgent\?/, 'main .asks');
  await tabTo(t, '[data-act="decline"][data-arg="sw"]', 'Decline', 20);
  await t.press('Enter', 'Decline');
  await t.expect('Focus is on the first reason, with a visible focus', ring(t.page), true);
  await t.press('Tab', 'Tab to Wrong version');
  await t.press('Enter', 'Pick Wrong version', { decision: true });
  await t.expect('The pick keeps focus', focused(t.page), 'button[declinePick=Wrong version]');
  await tabTo(t, '[data-act="declineYes"][data-arg="sw"]', 'Decline', 5);
  await t.expect('Decline has a visible focus', ring(t.page), true);
  await t.press('Enter', 'Decline', { decision: true, until: /Declined, nothing was written/ });
  await t.expectText('Declined with the reason', /Declined by Bob\. Nothing was written\. Reason: Wrong version\./, 'main #decision');
});


/* Step 3 fix pass. */
add('MARK-approval', 'With Mark what isn’t built on, Not checked, Ask, the question box, the questions and the decline reasons each carry a label', async (t) => {
  await t.setup(async (k) => { await ctl(k, 'markUnbuilt', 'on'); await k.setUser('bob'); });
  await t.click(S.review, 'Review and decide');
  const label = (sel) => t.page.$eval(sel, (el) => el.getAttribute('data-unbuilt')).catch(() => 'not marked');
  await t.expect('Not checked is marked', label('main #decision dl.unchecked'), /Not checked/);
  await t.expect('Ask is marked', label('main #decision p:has(> [data-act="askOpen"])'), /Ask the requester/);
  await t.click('main [data-act="askOpen"][data-arg="sw"]', 'Ask Carol a question');
  await t.expect('The question box is marked', label('main #decision form.askbox'), /Ask the requester/);
  await t.field('#ask-sw', 'Is this urgent?', 'Type the question');
  await t.click('main form[data-submit="askSend"] button[type="submit"]', 'Send question');
  await t.expect('The questions are marked', label('main #decision .asks'), /Questions on a request/);
  await t.click('main [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.expect('The decline reasons are marked', label('main #decision .decide'), /Reasons for a decline/);
});

add('RUN-retry-panel', 'A retry in the side panel puts focus on the panel’s heading, and #app stays put', async (t) => {
  await t.ask('Why did Morning new-ticket check stop?');
  await t.click(`${lastCard} [data-act="run"][data-arg="issues"]`, 'See the run');
  await t.click('#sidepanel [data-act="retryIssues"]', 'Retry the run', { decision: true });
  await t.expect('Focus is on the panel’s heading', focused(t.page), 'h2#sp-h');
  await t.expectText('The panel shows the retry done', /Done, nothing new today/, '#sidepanel');
  await t.expect('#app has not scrolled', appScroll(t), 0);
}, [1280, 390]);

add('APPR-decide-nav', 'A half-picked decline reason doesn’t survive leaving the page', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click('main [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.click('main [data-act="declinePick"][data-arg="Wrong version"]', 'Wrong version');
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.review, 'Review and decide again');
  await t.expectCount('The reasons are closed', 'main .decide [data-act="declinePick"]', 0);
  await t.expectCount('Approve and Decline are back', 'main :is([data-act="approve"], [data-act="decline"])[data-arg="sw"]', 2);
});

add('APPR-thread-kept', 'Once a request is decided its questions stay on the record, read only, for the Approver and the requester', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click(S.review, 'Review and decide');
  await t.click('main [data-act="askOpen"][data-arg="sw"]', 'Ask Carol a question');
  await t.field('#ask-sw', 'Is this urgent?', 'Type the question');
  await t.click('main form[data-submit="askSend"] button[type="submit"]', 'Send question');
  await t.click('main [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.click('main [data-act="declineYes"][data-arg="sw"]', 'Decline', { decision: true, until: /Declined, nothing was written/ });
  await t.expectText('The question is on the record', /You asked Carol: Is this urgent\?\s+Not answered before the request was decided\./, 'main #decision');
  await t.expectCount('No question or answer box', 'main :is([data-act="askOpen"], form.askbox)', 0);
  await t.setup(async (k) => {
    await k.setUser('alice'); await k.go('home');
    await testRunWaiting(k);
    await k.setUser('bob'); await k.go('home');
    await k.page.click('main [data-act="run"][data-arg="conf"]'); await k.settle();
    await k.page.click('main [data-act="askOpen"][data-arg="conf"]'); await k.settle();
    await k.page.fill('#ask-conf', 'Should MOCK-31 be in this summary?');
    await k.page.click('main form[data-submit="askSend"] button[type="submit"]'); await k.settle();
    await k.setUser('alice');
    await ctl(k, 'yesAs', 'siti');
    await k.waitText(/Siti approved, and the platform/);
    await k.settle();
  });
  await t.expectText('Alice sees Bob’s question on the approved run', /Bob asked you: Should MOCK-31 be in this summary\?\s+Not answered before the request was decided\./, 'main #decision');
  await t.expectCount('Alice has no answer box once it is decided', 'main form.askbox', 0);
});

add('DECLINED-access', 'When the second Approver declines after the first said yes, the record says both, in the run and in Teams', async (t) => {
  await t.setup(async (k) => {
    await ctl(k, 'preview', 'on');
    await k.setUser('bob'); await k.go('home');
    await k.page.click('main [data-act="run"][data-arg="access"]'); await k.settle();
    await k.page.click('main [data-act="approve"][data-arg="access"]'); await k.settle();
    await k.setUser('alice'); await k.go('workflows');
  });
  await t.click('main [data-act="run"][data-arg="access"]:has-text("Review and decide")', 'Review and decide');
  await t.click('main [data-act="decline"][data-arg="access"]', 'Decline');
  await t.click('main [data-act="declinePick"][data-arg="Someone still needs access"]', 'Someone still needs access', { decision: true });
  await t.click('main [data-act="declineYes"][data-arg="access"]', 'Decline', { decision: true, until: /Declined, nothing was removed/ });
  await t.expectText('The run’s record says both', /Approved by Bob, then declined by Alice\. Nothing was removed\. Reason: Someone still needs access\./, 'main #decision');
  await t.click(S.teams, 'Open Teams');
  await t.expectText('Teams says both', /Approved by Bob at 9:10 today, then declined by Alice at 9:10 today\s+Nothing was removed\. Reason: Someone still needs access\./, '.drawer');
});

add('WF-last-run', 'Workflows rows and the chat’s check card give each workflow’s last run from one source, a declined run included, each on one line', async (t) => {
  await t.setup(async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await k.setUser('alice'); });
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('The row says the last run was declined', /Keep our software up to date[\s\S]{0,400}Last run Mon 26 Oct · Declined by Bob/, 'main .wf-list');
  await t.expectText('The stopped one says it stopped', /Morning new-ticket check[\s\S]{0,400}Last run Today 8:00 · Stopped/, 'main .wf-list');
  const lines = (sel) => t.page.$$eval(sel, (els) => els.map((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight))));
  await t.expect('Each row’s last run is one line', lines('main .wf-last'), (v) => v.length >= 3 && v.every((n) => n === 1));
  await t.menu('home', 'Back to Chat');
  await t.ask(CHECK_WORKFLOWS);
  await t.expectText('The check card agrees', /Keep our software up to date\s+On\s+Next run[^\n]*\s+Last run Mon 26 Oct · Declined by Bob/, lastCard);
  await t.expect('Each card line is one line', lines(`${lastCard} .row-last`), (v) => v.length >= 3 && v.every((n) => n === 1));
}, [1280, 390]);

/* Roles (ADR 0043, step 4): the Approver's box for questions only, read-only pages for him, and n8n views only for
   people with n8n access. Checked at web widths only: since 11 Nov the Portal is a desktop web app, and approvals on a
   phone happen in Teams. */
const CHANGE_CONTROLS = ':is([data-act="turnOn"], [data-act="editSave"], [data-act="watchAdd"], [data-act="instead"], [data-act="pause"], [data-act="resume"], [data-act="retryIssues"], [data-act="retryNudge"], [data-act="report"], [data-act="stopAsk"], [data-act="answer"], [data-act="checkNow"], [data-act="editSched"], [data-act="menu"], [data-act="askDelete"], [data-act="removeSw"], [data-act="useNewAddress"], [data-act="n8nAsk"], [data-act="n8nNew"], [data-act="editAppr"], [data-act="askPlanner"], #sw-name)';
const OPS = /^Operators set up workflows\. Ask Alice or Carol\.$/;
const N8N_WORDS = (v) => !/n8n/i.test(v);
const panelHas = (k, sel, n) => k.page.waitForFunction(([s, c]) => document.querySelectorAll(s).length === c, [sel, n]);
/* A button that isn't drawn for this person, put into the page by hand: the action itself must refuse it. */
const forge = (k, act, arg) => k.page.evaluate(([a, g]) => { const b = document.createElement('button'); b.dataset.act = a; if (g) b.dataset.arg = g; b.id = 'forged'; b.textContent = 'forged'; document.querySelector('main').appendChild(b); b.click(); }, [act, arg]);
const whoLine = async (k) => { await k.page.$eval('.testctl-toggle', (b) => b.click()); const v = await k.page.innerText('.testctl-who'); await k.page.$eval('.testctl-toggle', (b) => b.click()); return v; };

add('ROLE-home', 'Bob’s Home starts calm, with the Planner’s box for questions, three suggestions for an Approver and Needs you under them', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.expectCount('Bob has the Planner’s box', 'main [data-ask]', 1);
  await t.expectText('The greeting says what waits for him', /Good morning! Bob\s+1 request is waiting for your yes\./, 'main .welcome');
  await t.expect('Three suggestions, each a question', t.page.$$eval('main .examples .chip', (cs) => cs.map((c) => c.textContent).join(' | ')), 'What is waiting for my yes? | What did I decide before? | How are the workflows doing?');
  const at = await t.page.evaluate(() => {
    const box = (s) => { const el = document.querySelector(s); return el ? el.getBoundingClientRect() : null; };
    const main = box('main .home');
    return { tops: ['main .welcome .face', 'main .welcome h1', 'main form.composer', 'main .examples', 'main #needs-h'].map((s) => (box(s) ? Math.round(box(s).top) : -1)), mid: Math.round(main.left + main.width / 2), centres: ['main .welcome .face', 'main form.composer'].map((s) => Math.round(box(s).left + box(s).width / 2)) };
  });
  await t.expect('Bot, heading, box, suggestions, then Needs you, top to bottom', at.tops, (v) => v.every((x, i) => x >= 0 && (i === 0 || x > v[i - 1])));
  await t.expect('The bot and the box are centred', at, (v) => v.centres.every((c) => Math.abs(c - v.mid) <= 2));
  await t.expectText('Needs you has his request, with Review and decide', /3 upgrade tickets are waiting for your yes[\s\S]*Review and decide/, 'main section[aria-labelledby="needs-h"]');
  await t.expectCount('No control that changes anything', `main ${CHANGE_CONTROLS}`, 0);
  await t.expectCount('No pinned line and no thread before his first message', 'main :is(.pinned, .thread)', 0);
}, [1280, 768]);

add('ROLE-asks', 'Bob asks what waits for his yes, what he decided and how things are doing, and each answer comes from platform state with no control that changes anything', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click('main .examples [data-act="example"][data-arg="0"]', 'What is waiting for my yes?', { reply: true });
  await t.expect('The answer is Home’s line', lastSay(t), '1 request is waiting for your yes.');
  await t.expectText('Its card has the request with Review and decide', /3 upgrade tickets are waiting for your yes[\s\S]*Review and decide/, lastCard);
  await t.ask('What did I decide before?');
  await t.expect('He has decided twice before', lastSay(t), 'Here are your 2 decisions.');
  await t.expectText('Each with its workflow, Approved and when', /Morning new-ticket check\s+Approved\s+Approved by Bob, Mon 26 Oct, 8:00\. 1 ticket created \(MOCK-12\)\.\s+Weekly closed-ticket summary\s+Approved\s+Approved by Bob, Fri 16 Oct, 16:00\. 1 ticket created \(MOCK-11\)\./, lastCard);
  await t.expect('Alice’s decision is not his', t.page.innerText(lastCard), (v) => !/Alice/.test(v));
  await t.ask('How are the workflows doing?');
  await t.expect('The team’s workflows, not his own', lastSay(t), /^The team has 3 workflows\./);
  await t.ask('Is LangGraph up to date?');
  await t.expect('A version question', lastSay(t), 'LangGraph is behind. You run 1.2.14 and the newest is 1.2.17.');
  await t.ask('Why did Morning new-ticket check stop?');
  await t.expectText('The troubleshooter’s answers, with who can retry and no Retry', /What happened[\s\S]*Safe to retry[\s\S]*An Operator can retry the run\./, lastCard);
  await t.ask('What can you do?');
  await t.expectText('What an Approver can ask, and who sets up workflows', /What is waiting for your yes[\s\S]*What you decided before[\s\S]*Operators set up workflows\. Ask Alice or Carol\./, lastCard);
  await t.expectCount('No control that changes anything, in any answer', `main .thread ${CHANGE_CONTROLS}`, 0);
  await t.expect('#app has not scrolled', appScroll(t), 0);
}, [1280]);

add('ROLE-refuse', 'Bob’s requests to set up, change a schedule, pause or watch get “Operators set up workflows.” and the Operators’ names, never a card that changes anything', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  const asks = [WEEKLY_SUMMARY, 'Make the morning new-ticket check run on Mondays only', 'Pause the weekly closed-ticket summary', 'Watch Redis releases', 'Keep track of the React version', 'set up another workflow',
    'Could you make the morning check daily?', 'What is waiting for my yes, and pause the morning new-ticket check', 'How are the workflows doing? Then delete the weekly summary'];
  for (const q of asks) {
    await t.ask(q);
    await t.expect(`“${q}” gets the refusal`, lastSay(t), OPS);
    await t.expectCount(`“${q}” gets no card`, `${lastCard} [data-pres]`, 0);
  }
  await t.ask('approve the upgrade tickets');
  await t.expect('Approve gets the request to open, never a decision in the chat', lastSay(t), 'I can’t approve or decline for you. Open the request to see exactly what it will write, and decide there.');
  await t.expectCount('…with Review and decide', `${lastCard} [data-act="run"][data-arg="sw"]`, 1);
  await t.ask('Approve it automatically');
  await t.expectText('Approving by itself is refused, with how approvals work and nothing to set up', /How approvals work[\s\S]*Nobody approves their own work/, lastCard);
  await t.expectCount('No Approve or Decline in the chat', 'main .thread :is([data-act="approve"], [data-act="decline"])', 0);
  await t.expectCount('No control that changes anything, in any answer', `main .thread ${CHANGE_CONTROLS}`, 0);
}, [1280]);

add('ROLE-read-only', 'Bob’s Workflows, a workflow’s page and the Watchlist are read only, with no dead button, and one note on each says who makes changes', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  const pages = [['Workflows', () => t.menu('workflows', 'Open Workflows')], ['Morning new-ticket check', () => t.click(S.row('issues'), 'Open Morning new-ticket check')], ['the Watchlist', () => t.menu('software', 'Open the Watchlist')]];
  for (const preview of [false, true]) {
    if (preview) await t.setup((k) => ctl(k, 'preview', 'on'));
    for (const [label, open] of pages) {
      const where = `${label}${preview ? ', Planned shown' : ''}`;
      await open();
      await t.expectCount(`${where}: no control that changes anything`, `main ${CHANGE_CONTROLS}`, 0);
      await t.expectCount(`${where}: no dead button`, 'main :is(button:disabled, [aria-disabled="true"])', 0);
      await t.expectCount(`${where}: one note says who makes changes`, 'main .ops-note', 1);
      await t.expectText(`${where}: it names the Operators`, /^Only Operators change [a-z ]+\. Ask Alice or Carol\.$/, 'main .ops-note');
    }
  }
  await t.setup((k) => forge(k, 'checkNow'));
  await t.expectText('A change control put into the page by hand is refused by the action', /Operators set up workflows\. Ask Alice or Carol\./, '.toast');
  await t.setup(async (k) => { await k.go('workflows'); await forge(k, 'pause', 'issues'); });
  await t.expect('…and nothing changed', t.page.innerText('main .wf-list'), (v) => !/Paused/.test(v));
}, [1280, 768]);

add('ROLE-offline', 'With no AI model, Bob’s Home says the Planner can’t answer and who can connect one, and keeps his request first', async (t) => {
  await t.setup(async (k) => { await k.setUser('bob'); await ctl(k, 'modelOn', 'off'); });
  await t.expectText('The Home says why and who can fix it', /I can’t answer questions until an AI model is connected\s+An Operator can connect one in Settings\. 1 request is waiting for your yes\./, 'main .welcome');
  await t.expectCount('No box while there is no model', 'main [data-ask]', 0);
  await t.expectCount('No Connect a model button, which only an Operator can use', 'main [data-act="setGo"]', 0);
  await t.expectCount('His request, with Review and decide', 'main section[aria-labelledby="needs-h"] .btn.primary[data-act="run"][data-arg="sw"]', 1);
}, [1280]);

add('ROLE-own-chat', 'Each person has their own chat: Bob never sees Alice’s conversation, and hers is there when she comes back', async (t) => {
  await t.ask(CHECK_WORKFLOWS);
  await t.setup((k) => k.setUser('bob'));
  await t.expectCount('Bob’s Home starts calm, with no thread', 'main .thread', 0);
  await t.expectCount('…and his own box', 'main [data-ask]', 1);
  await t.ask('What did I decide before?');
  await t.expect('His chat has only his question', t.page.innerText('main .thread'), (v) => /What did I decide before\?/.test(v) && !/Check my workflows/.test(v));
  await t.setup((k) => k.setUser('alice'));
  await t.expect('Alice’s chat is as she left it', t.page.innerText('main .thread'), (v) => /Check my workflows/.test(v) && !/What did I decide before/.test(v));
}, [1280]);

add('ROLE-decision', 'Bob’s whole decision: from Needs you, a question to the requester, a decline with a reason, another approval, then the Planner lists both with when and the reason', async (t) => {
  await t.setup(async (k) => { await testRunWaiting(k); await k.setUser('bob'); await k.go('home'); });
  await t.expectText('Two requests wait for him', /2 requests are waiting for your yes\./, 'main .welcome');
  await t.click('main section[aria-labelledby="needs-h"] [data-act="run"][data-arg="sw"]', 'Review and decide the upgrade tickets, from Needs you');
  await t.click('main [data-act="askOpen"][data-arg="sw"]', 'Ask Carol a question');
  await t.field('#ask-sw', 'Has FastAPI 0.120.1 been tried with our login service?', 'Type the question');
  await t.click('main form[data-submit="askSend"] button[type="submit"]', 'Send question');
  await t.click('main [data-act="decline"][data-arg="sw"]', 'Decline');
  await t.click('main [data-act="declinePick"][data-arg="Wrong version"]', 'Wrong version', { decision: true });
  await t.click('main [data-act="declineYes"][data-arg="sw"]', 'Decline', { decision: true, until: /Declined, nothing was written/ });
  await t.menu('home', 'Back to Chat');
  await t.expectText('One request is left', /1 request is waiting for your yes\./, 'main .welcome');
  await t.click('main section[aria-labelledby="needs-h"] [data-act="run"][data-arg="conf"]', 'Review and decide the test run');
  await t.click('main [data-act="approve"][data-arg="conf"]', 'Approve', { decision: true, until: /Bob approved, and the platform created/ });
  await t.menu('home', 'Back to Chat');
  await t.expectText('Nothing waits any more', /Nothing needs you right now\./, 'main .welcome');
  await t.ask('What did I decide before?');
  const card = t.page.innerText(lastCard);
  await t.expect('Four decisions', lastSay(t), 'Here are your 4 decisions.');
  await t.expect('The decline today, with its reason, as Teams says it', card, /Keep our software up to date\s+Declined\s+Declined by Bob at 9:10 today\. Nothing was written\. Reason: Wrong version\./);
  await t.expect('The approval today', card, /Friday closed ticket summary\s+Approved\s+Approved by Bob at 9:10 today\./);
  await t.expect('Today’s come before the earlier ones', card, /9:10 today[\s\S]*9:10 today[\s\S]*Mon 26 Oct[\s\S]*Fri 16 Oct/);
}, [1280, 1024]);

add('ROLE-panel', 'Bob decides in the side panel from his chat: focus goes to the panel’s heading, #app stays put, and his card follows', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.ask('What is waiting for my yes?');
  await t.click(`${lastCard} [data-act="run"][data-arg="sw"]`, 'Review and decide, from the card');
  await t.expectCount('The request opens in the side panel', '#sidepanel [data-act="approve"][data-arg="sw"]', 1);
  await t.click('#sidepanel [data-act="approve"][data-arg="sw"]', 'Approve', { decision: true, until: /3 tickets created in Jira/ });
  await t.expectText('The panel shows the run done', /Done\s+3 tickets created in Jira/, '#sidepanel');
  await t.expect('Focus is on the panel’s heading', focused(t.page), 'h2#sp-h');
  await t.expect('#app has not scrolled', appScroll(t), 0);
  await t.click('#sidepanel [data-act="panelClose"]', 'Close');
  await t.expectText('His card in the chat follows', /Nothing needs you right now\./, lastCard);
}, [1280, 901]);

add('N8N-shown', 'Carol has n8n access: with Planned features shown she sees the n8n blocks go in while the Planner builds, the blocks on a workflow’s page, and Open in n8n', async (t) => {
  await t.setup(async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); });
  await t.expect('The person switch says she has n8n access', whoLine(t.kit), 'Operator, with n8n access');
  await t.ask(WEEKLY_SUMMARY);
  await t.setup((k) => panelHas(k, '#sidepanel .n8n-canvas > li', 5));
  await t.expectText('The side panel shows the n8n blocks', /Schedule, still to choose\s+Jira reader\s+Summary writer\s+Ask for a yes\s+Make the approved changes/, '#sidepanel .n8n-canvas');
  await t.expectCount('…tagged Planned', '#sidepanel .tag.planned', 1);
  await t.expect('The panel widens while it builds', t.page.evaluate(() => Math.round(document.querySelector('#sidepanel').getBoundingClientRect().width)), (w) => w > 420);
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Workflows offers Start in n8n', /Start in n8n/);
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('main details.tech > summary', 'Technical details');
  await t.expectText('The page shows its blocks in n8n', /In n8n\s+PLANNED\s+Every weekday at 8:00\s+Jira reader\s+Summary writer\s+Ask for a yes\s+Make the approved changes/i, 'main details.tech');
  await t.click(S.more, 'More actions');
  await t.click(S.pick('n8nAsk', 'issues'), 'Open in n8n');
  await t.expectText('The n8n dialog opens', /Open “Morning new-ticket check” in n8n/, '.dialog');
  await t.press('Escape', 'Close the dialog');
  await t.menu('home', 'Back to Chat');
  await t.ask('open the weekly closed-ticket summary in n8n');
  await t.expectCount('The Planner offers Open it in n8n', `${lastCard} [data-act="n8nAsk"][data-arg="nudge"]`, 1);
}, [1280, 1024]);

add('N8N-hidden', 'Without n8n access, Alice and Bob see the plain steps and no n8n words, even with Planned features shown, and asking to open n8n is refused', async (t) => {
  await t.setup((k) => ctl(k, 'preview', 'on'));
  await t.expect('The person switch shows no n8n access', whoLine(t.kit), 'Operator and Approver');
  await t.ask(WEEKLY_SUMMARY);
  await t.setup((k) => panelHas(k, '#sidepanel .steps > li', 3));
  await t.expect('Alice’s side panel has the plain steps and no n8n words', t.page.innerText('#sidepanel'), N8N_WORDS);
  await t.ask('open the morning new-ticket check in n8n');
  await t.expect('Opening n8n is refused, with where to add it', lastSay(t), 'Only people with n8n access can open n8n. You can add it in Settings, under People and permissions.');
  await t.expectCount('…and no Open in n8n', `${lastCard} [data-act="n8nAsk"]`, 0);
  await t.expectCount('…but a button to where n8n access is given', `${lastCard} [data-act="setGo"][data-arg="people"]`, 1);
  await t.menu('workflows', 'Open Workflows');
  await t.expect('Workflows has no Start in n8n', t.page.innerText('main'), N8N_WORDS);
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('main details.tech > summary', 'Technical details');
  await t.click(S.more, 'More actions');
  await t.expect('The page and its menu have no n8n', t.page.innerText('main'), N8N_WORDS);
  await t.press('Escape', 'Close the menu');
  await t.setup((k) => ctl(k, 'n8nChange', 'issues'));
  await t.expectText('Carol’s change is named, without where it was made', /Carol’s change removed Ask for a yes/, 'main article.task');
  await t.expect('…so the page still has no n8n words', t.page.innerText('main'), N8N_WORDS);
  await t.setup((k) => forge(k, 'n8nAsk', 'issues'));
  await t.expectCount('A forged Open in n8n is refused by the action', '.dialog', 0);
  await t.setup(async (k) => { await k.setUser('bob'); await k.go('home'); });
  await t.ask('open n8n');
  await t.expect('Bob is refused too', lastSay(t), 'Only people with n8n access can open n8n, and only Operators can have it.');
}, [1280]);

add('N8N-settings', 'n8n access is set in Settings, People and permissions, for Operators only, and giving it to Alice shows her the n8n views', async (t) => {
  await t.setup((k) => ctl(k, 'preview', 'on'));
  await t.click('.hdr [data-act="go"][data-arg="settings"]', 'Settings');
  await t.click('[data-act="setTab"][data-arg="people"]', 'People and permissions');
  await t.expect('Only the Operators, Alice and Carol, have an n8n access box, and Carol’s is ticked', t.page.$$eval('main [data-role$=":n8n"]', (bs) => bs.map((b) => `${b.dataset.role}=${b.checked}`).join(' ')), 'alice:n8n=false carol:n8n=true');
  await t.expectCount('Each box is tagged Planned', 'main label:has([data-role$=":n8n"]) .tag.planned', 2);
  await t.expectText('The rule is said', /Only Operators can have n8n access/);
  await t.click('main [data-role="alice:n8n"]', 'Give Alice n8n access', { decision: true });
  await t.expect('The person switch says so', whoLine(t.kit), 'Operator and Approver, with n8n access');
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click(S.more, 'More actions');
  await t.expectCount('Alice now has Open in n8n', S.pick('n8nAsk', 'issues'), 1);
  await t.setup(async (k) => { await k.page.keyboard.press('Escape'); await k.page.click('.hdr [data-act="go"][data-arg="settings"]'); await k.settle(); await k.page.click('[data-act="setTab"][data-arg="people"]'); await k.settle(); });
  await t.click('main [data-role="carol:n8n"]', 'Take away Carol’s n8n access', { decision: true });
  await t.setup((k) => k.setUser('carol'));
  await t.expect('Carol has none now', whoLine(t.kit), 'Operator');
  await t.setup(async (k) => { await k.go('workflows'); await k.page.click(S.row('issues')); await k.settle(); await k.page.click('main details.tech > summary'); await k.settle(); });
  await t.expect('…so her workflow page has no n8n words', t.page.innerText('main'), N8N_WORDS);
}, [1280]);

add('MARK-roles', 'With Mark what isn’t built on, Bob’s box, his decisions card, the read-only note, the n8n blocks and the n8n access box each carry a label', async (t) => {
  await t.setup(async (k) => { await ctl(k, 'markUnbuilt', 'on'); await k.setUser('bob'); });
  await t.expect('Bob’s Home with the box', t.page.getAttribute('main .home.planner', 'data-unbuilt'), /Approver’s box/);
  await t.ask('What did I decide before?');
  await t.expectCount('His decisions card', `${lastCard} .pcard[data-unbuilt*="decisions"]`, 1);
  await t.menu('workflows', 'Open Workflows');
  await t.expectCount('The read-only note', 'main .ops-note[data-unbuilt]', 1);
  await t.setup(async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); await k.go('home'); });
  await t.ask(WEEKLY_SUMMARY);
  await t.setup((k) => panelHas(k, '#sidepanel .n8n-canvas > li', 5));
  await t.expectCount('The n8n blocks in the side panel', '#sidepanel [data-unbuilt*="n8n blocks"]', 1);
  await t.click('.hdr [data-act="go"][data-arg="settings"]', 'Settings');
  await t.click('[data-act="setTab"][data-arg="people"]', 'People and permissions');
  await t.expectCount('Each n8n access box, and its rule', 'main [data-unbuilt="n8n access (ADR 0043)"]', 3);
  await t.expect('Every one of them is outlined', t.page.$$eval('main [data-unbuilt], #sidepanel [data-unbuilt]', (els) => els.every((el) => getComputedStyle(el).outlineStyle !== 'none')), true);
}, [1280]);

add('KEYS-ROLE', 'With the keyboard only, Bob reaches his box, asks, and reaches Review and decide in the answer, each stop with a visible focus', async (t) => {
  await t.setup(async (k) => { await k.setUser('bob'); await focusTop(k); });
  await tabTo(t, '[data-ask]', 'the Planner’s box');
  await t.expect('The box shows its focus', t.page.evaluate(() => getComputedStyle(document.activeElement.closest('form.composer')).outlineStyle !== 'none'), true);
  await t.setup((k) => k.page.keyboard.type('What is waiting for my yes?'));
  await t.press('Enter', 'Send', { reply: true });
  await tabTo(t, `${lastCard} [data-act="run"][data-arg="sw"]`, 'Review and decide in the answer');
  await t.expect('Review and decide shows its focus', ring(t.page), true);
  await t.press('Enter', 'Open it');
  await t.expectCount('The request opens in the side panel', '#sidepanel [data-act="approve"][data-arg="sw"]', 1);
}, [1280]);

/* Step 4 fix pass: the independent review's findings, and defects from steps 1 to 3 found while the spec was rewritten.
   Each failed on the prototype before the fix. */
/* Escape takes the last message away first, so the one read is the action's own. */
const toastAfter = async (k, act, arg) => {
  await k.page.keyboard.press('Escape');
  await k.settle(450);
  await forge(k, act, arg);
  await k.settle(200);
  return k.page.locator('.toast').innerText().catch(() => '(no toast)');
};
const OPS_TOAST = /^Operators set up workflows\. Ask Alice or Carol\./;

add('FIX-deny-default', 'An Approver is refused every change, including Settings, agents and asking the team: the actions deny anything not opened to him', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  for (const [act, arg] of [['limitSave'], ['agentRestore', 'jira:1'], ['agentDiscard'], ['connReplace', 'jira'], ['connSave'], ['modelConnect'], ['modelSave'], ['teamReq', 'Slack|ask'], ['askTeamOffline'], ['toolAskGo'], ['askPlanner']]) {
    await t.expect(`${act} is refused`, toastAfter(t.kit, act, arg), OPS_TOAST);
  }
  await t.setup(async (k) => { await k.go('workflows'); await forge(k, 'filter', 'stopped'); await k.settle(); });
  await t.expectCount('Reading still works: the Stopped filter is on', 'main [data-act="filter"][data-arg="stopped"][aria-pressed="true"]', 1);
}, [1280]);

add('FIX-name-not-command', 'A question about a workflow whose name holds a schedule word, such as “weekly”, gets its state, for Bob and for Alice', async (t) => {
  const q = 'how is the weekly closed-ticket summary doing?';
  await t.setup((k) => k.setUser('bob'));
  await t.ask(q);
  await t.expect('Bob gets its state', lastSay(t), /^Weekly closed-ticket summary stopped\. Its next run is /);
  await t.setup((k) => k.setUser('alice'));
  await t.ask(q);
  await t.expect('Alice gets its state', lastSay(t), /^Weekly closed-ticket summary stopped\. Its next run is /);
  await t.expectCount('…and no set-up card', `${lastCard} [data-act="turnOn"]`, 0);
}, [1280]);

add('FIX-decided-whole', 'Asking to see past decisions reads the whole question, with no part marked as not followed', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.ask('show my past decisions');
  await t.expect('The decisions', lastSay(t), 'Here are your 2 decisions.');
  await t.expectCount('No cross on any part of the question', `${lastCard} .part[data-mark="no"]`, 0);
}, [1280]);

add('FIX-approve-any-object', 'An Approver’s approve or decline goes to the request whatever it names, and a second change in the same request is still refused', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  for (const q of ['approve the upgrade', 'decline that request', 'approve it']) {
    await t.ask(q);
    await t.expect(`“${q}” gets the request to open`, lastSay(t), /^I can’t approve or decline for you\./);
  }
  await t.ask('approve the upgrade and pause the morning new-ticket check');
  await t.expect('A second change is still refused', lastSay(t), /^Operators set up workflows\./);
}, [1280]);

add('FIX-decisions-detail', 'Today’s decisions carry their outcome from the run page, and asking about declines lists only declines', async (t) => {
  await t.setup(async (k) => { await k.setUser('bob'); await k.go('home'); await k.page.click('main [data-act="run"][data-arg="sw"]'); await k.settle(); await k.page.click('main [data-act="approve"][data-arg="sw"]'); await k.waitText(approvedText); await k.settle(); await k.go('home'); });
  await t.ask('did I decline anything?');
  await t.expect('No declines yet, and no approvals listed', lastSay(t), 'You haven’t declined any requests yet.');
  await t.expectCount('…no rows', `${lastCard} li.row`, 0);
  await t.ask('What did I decide before?');
  await t.expectText('Today’s approval says what it did, as the run page does', /Keep our software up to date\s+Approved\s+Approved by Bob at 9:10 today\. 3 tickets created in Jira\./, lastCard);
}, [1280]);

add('FIX-bob-settings', 'Bob’s People and permissions is text he can read, with no control he can’t use', async (t) => {
  await t.setup((k) => k.setUser('bob'));
  await t.click('.hdr [data-act="go"][data-arg="settings"]', 'Settings');
  await t.click('[data-act="setTab"][data-arg="people"]', 'People and permissions');
  await t.expectCount('No dead control', 'main :is(input:disabled, button:disabled, [aria-disabled="true"])', 0);
  await t.expectText('Each person’s roles in words', /Alice[\s\S]*Operator and Approver[\s\S]*Bob[\s\S]*Approver/, 'main .people');
}, [1280]);

add('FIX-rail-count', 'The Watchlist count is for whoever can act on it: Alice’s agrees with the page, and Bob has none', async (t) => {
  const badge = (k) => k.page.locator('.rail .badge[data-val="sw-n"]').innerText().then((x) => x.replace(/\D+/g, '')).catch(() => 'none');
  await t.menu('software', 'Open the Watchlist');
  const page = await t.page.locator('main #sw-attn-h .count').innerText();
  await t.expect('Alice’s count agrees with Needs attention', badge(t.kit), page);
  await t.setup((k) => k.setUser('bob'));
  await t.expect('Bob has no Watchlist count', badge(t.kit), 'none');
}, [1280]);

add('FIX-wide', 'On a wide screen the header lines up with the page, Workflows rows use their width, and the chat sits next to its side panel', async (t) => {
  const left = (sel) => t.page.evaluate((s) => Math.round(document.querySelector(s).getBoundingClientRect().left), sel);
  await t.menu('workflows', 'Open Workflows');
  const brand = await left('.hdr .brand');
  await t.expect('The brand lines up with the page heading', left('main h1'), (v) => Math.abs(v - brand) <= 2);
  await t.expect('Each row’s last column ends at the row’s padding', t.page.$$eval('main .wf-row', (rows) => rows.map((r) => { const kids = [...r.children].filter((c) => c.getClientRects().length && !c.classList.contains('wf-last')); return Math.round(r.getBoundingClientRect().right - Math.max(...kids.map((c) => c.getBoundingClientRect().right))); })), (gaps) => gaps.length && gaps.every((g) => g <= 24));
  await t.menu('home', 'Back to Chat');
  await t.ask(CHECK_WORKFLOWS);
  await t.click(issuesRow, 'Open Morning new-ticket check from the card');
  await t.expect('The chat and the panel sit together', t.page.evaluate(() => Math.round(document.querySelector('#sidepanel').getBoundingClientRect().left - document.querySelector('.chatin').getBoundingClientRect().right)), (g) => g >= 0 && g <= 24);
}, [1920, 1440]);

add('FIX-starts-count', '“Set up another workflow” says as many places to start as it shows', async (t) => {
  await t.ask('set up another workflow');
  const n = await t.page.locator(`${lastCard} .starts .chip`).count();
  await t.expect('The sentence counts the chips', lastSay(t), n === 1 ? 'Here is a place to start. Pick it, or tell me something else.' : `Here are ${n} places to start. Pick one, or tell me something else.`);
}, [1280]);

add('FIX-offline-count', 'With no AI model, Needs you lists the model row it counts, pointing to the button above it', async (t) => {
  await t.setup((k) => ctl(k, 'modelOn', 'off'));
  await t.expectText('The first row is the model', /No AI model connected\s+Connect one with the button above\./, 'main section[aria-labelledby="needs-h"] li.nrow:first-child');
  await t.expectCount('…with no second Connect a model', 'main [data-act="setGo"][data-arg="model"]', 1);
}, [1280]);

add('FIX-gitlab', 'A request that reads a system the Planner can’t is a cross, and Set up the part I can sets it up on Jira', async (t) => {
  await t.ask('Every Monday at 9am, sum up the closed tickets from GitLab in MOCK');
  await t.expectText('The cross says what the part I can do reads', /Reads GitLab\s+I can only read [^\n]+, so the part I can do reads Jira tickets instead\./, lastCard);
  await t.click(`${lastCard} [data-act="turnOn"]`, 'Set up the part I can', { decision: true });
  await t.expectText('It is on, and says what was left out', /Monday closed ticket summary is on\.[\s\S]*Left out: Reads GitLab\./, lastCard);
}, [1280]);

add('FIX-day-choice', 'After choosing one of two days, the workflow keeps the chosen day and names only the other as left out', async (t) => {
  await t.ask('Every Monday and Friday at 9am, sum up the closed tickets in MOCK');
  await t.click(`${lastCard} [data-act="answer"][data-arg="day:Monday"]`, 'Monday', { decision: true });
  await t.expectText('The cross names Friday only', /“Friday”\s+I can only set one day, so it runs on Monday only\./, lastCard);
  await t.click(`${lastCard} [data-act="turnOn"]`, 'Set up the part I can', { decision: true });
  await t.expectText('Left out is Friday, not Monday', /Left out: “Friday”\./, lastCard);
}, [1280]);

add('FIX-edit-tickets', 'Changing a workflow made on Home to run every day changes the tickets it reads too, shown on the card and kept on its page', async (t) => {
  await t.setup((k) => turnOnWeekly(k));
  await t.ask('Make the friday closed ticket summary run every day');
  await t.expectText('The card shows the ticket change too', /Which tickets\s+Before\s+Tickets closed this week\s+After\s+Tickets closed in the last day/, lastCard);
  await t.click(`${lastCard} [data-act="editSave"]`, 'Save change', { decision: true });
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('conf'), 'Open Friday closed ticket summary');
  await t.expectText('Its page reads the day’s tickets', /Sums up tickets closed in the last day in MOCK/);
}, [1280]);

add('FIX-open-software', '“Open Redis on the Software page” opens Redis, for Alice and for Bob', async (t) => {
  for (const who of ['alice', 'bob']) {
    await t.setup((k) => k.setUser(who));
    await t.ask('Open Redis on the Software page');
    await t.expect(`${who}: Redis is on the watchlist`, lastSay(t), 'Redis is on the Software watchlist. Open it from here.');
    await t.click(`${lastCard} [data-open="software:ok:Redis"]`, 'Open Redis on the Software page');
    await t.expectText(`${who}: its row opens`, /Redis/, '#sidepanel');
    await t.click('#sidepanel [data-act="panelClose"]', 'Close');
  }
}, [1280]);

add('FIX-never-mind', 'A set-up card and an add-software card each have Never mind, which changes nothing', async (t) => {
  await t.ask(WEEKLY_SUMMARY);
  await t.click(`${lastCard} [data-act="discardDraft"][data-arg="live"]`, 'Never mind');
  await t.expectText('The draft is discarded, with Undo', /Discarded/, lastCard);
  await t.expectText('…and Undo', /Undo/, '.toast');
  await t.ask('Monitor Kubernetes releases');
  await t.click(`${lastCard} [data-act="watchKeep"]`, 'Never mind');
  await t.expectText('Nothing was added', /Not added\. Nothing changed\./, lastCard);
  await t.menu('software', 'Open the Watchlist');
  await t.expect('Kubernetes is not on the list', t.page.innerText('main .sw-table'), (v) => !/Kubernetes/.test(v));
}, [1280]);

add('FIX-mark-more', 'Mark what isn’t built outlines the run line, the three answers, the last-run line, the count line, the edit card, versions and the declined record', async (t) => {
  await t.setup((k) => ctl(k, 'markUnbuilt', 'on'));
  await t.ask('Make the morning new-ticket check run on Mondays only');
  await t.expectCount('The edit card', `${lastCard} .pcard[data-unbuilt*="edit card"]`, 1);
  await t.click(`${lastCard} [data-act="editSave"]`, 'Save change');
  await t.menu('workflows', 'Open Workflows');
  await t.expectCount('Each last-run line', 'main .wf-last[data-unbuilt]', 3);
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.expectCount('The versions', 'main ol.timeline[data-unbuilt*="Versions"]', 1);
  await t.click('main [data-act="watch"][data-arg="issues"]', 'See the run', { until: /Safe to retry/ });
  await t.expectCount('The run line', 'main ol.line[data-unbuilt]', 1);
  await t.expectCount('The three answers', 'main dl.qa3[data-unbuilt]', 1);
  await t.menu('software', 'Open the Watchlist');
  await t.expectCount('The count line', 'main .pagehead p[data-unbuilt*="count line"]', 1);
  await t.setup((k) => bobDeclines(k, 'sw', 'Wrong version'));
  await t.expectCount('The declined record', 'main p[data-unbuilt*="declined record"]', 1);
}, [1280]);

add('FIX-run-times', 'Each entry in a run page’s log has its time, the first with its day', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.click(S.row('issues'), 'Open Morning new-ticket check');
  await t.click('main [data-act="watch"][data-arg="issues"]', 'See the run', { until: /Safe to retry/ });
  await t.setup(async (k) => { if (!(await k.page.$('#run-detail'))) { await k.page.click('main [data-act="runDetail"]'); await k.settle(); } });
  const times = await t.page.$$eval('#run-detail .chat > li:not(.typing)', (ls) => ls.map((l) => (l.querySelector('time.log-at') || {}).textContent || (l.querySelector('.faces') ? 'joined' : '')));
  await t.expect('Every entry but the “joined” line has a time', times, (v) => v.length >= 3 && v.every((x) => x === 'joined' || /\d:\d\d$/.test(x)));
  await t.expect('The first says its day', times[0], /^Tue 27 Oct, 8:00$/);
}, [1280]);

/* Screens shot by shots.cjs and measured by quality.cjs. prepare(k) sets the screen up like a user would reach it. */
const open = async (k, sel) => { await k.page.click(sel); await k.settle(); };
/* While chatting, only the side panel's body scrolls: bring a part of it to the top of the panel. */
const inPanel = (k, sel) => k.page.evaluate((s) => { const el = document.querySelector(s); const body = el && el.closest('.sp-body'); if (body) body.scrollTop += el.getBoundingClientRect().top - body.getBoundingClientRect().top - 8; }, sel);
const screens = [
  { name: 'day-one-home', prepare: async (k) => { await k.setDay('one'); } },
  { name: 'home', prepare: async () => {} },
  { name: 'approver-home', prepare: async (k) => { await k.setUser('bob'); } },
  { name: 'planner-setup-card', prepare: async (k) => { await k.ask(WEEKLY_SUMMARY); } },
  { name: 'planner-cant-email', prepare: async (k) => { await k.ask(EMAIL); } },
  { name: 'planner-watch-kubernetes', prepare: async (k) => { await k.ask('Monitor Kubernetes releases'); } },
  { name: 'workflows', prepare: async (k) => { await k.go('workflows'); } },
  { name: 'workflow-page', prepare: async (k) => { await k.go('workflows'); await open(k, S.row('issues')); } },
  { name: 'run-stopped', prepare: async (k) => { await k.go('workflows'); await open(k, S.seeRun); } },
  { name: 'run-approval', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); } },
  { name: 'software', prepare: async (k) => { await k.go('software'); } },
  { name: 'agent-library', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="setTab"][data-arg="how"]'); await open(k, '[data-act="libTab"][data-arg="agents"]'); } },
  { name: 'agent-library-tools', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="setTab"][data-arg="how"]'); await open(k, '[data-act="libTab"][data-arg="tools"]'); } },
  { name: 'settings-connections', prepare: async (k) => { await open(k, '.hdr [data-act="go"][data-arg="settings"]'); await open(k, '[data-act="setTab"][data-arg="connections"]'); } },
  { name: 'teams-drawer', prepare: async (k) => { await open(k, S.teams); } },
  { name: 'drafts', prepare: async (k) => { await k.ask(WEEKLY_SUMMARY); await open(k, '[data-act="newChat"]'); await k.go('workflows'); } },
  { name: 'home-needs-you', prepare: async (k) => { await k.page.evaluate(() => { const h = [...document.querySelectorAll('main h2')].find((x) => /Needs you/.test(x.textContent)); if (h) h.scrollIntoView(); }); } },
  { name: 'planner-check-workflows', prepare: async (k) => { await open(k, S.example(0)); } },
  { name: 'planner-why-stopped', prepare: async (k) => { await k.ask('Why did Morning new-ticket check stop?'); } },
  { name: 'workflow-more-menu', prepare: async (k) => { await k.go('workflows'); await open(k, S.row('issues')); await open(k, S.more); } },
  { name: 'run-detailed-activity', prepare: async (k) => { await k.go('workflows'); await open(k, S.seeRun); await open(k, 'main [data-act="runDetail"]'); } },
  { name: 'software-attention', prepare: async (k) => { await k.go('software'); await k.page.evaluate(() => { const h = document.getElementById('sw-attn-h'); if (h) h.scrollIntoView(); }); } },
  { name: 'library-what-it-can-do', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="setTab"][data-arg="how"]'); } },
  { name: 'offline-home', prepare: async (k) => { await ctl(k, 'modelOn', 'off'); } },
  { name: 'preview-software', prepare: async (k) => { await ctl(k, 'preview', 'on'); await k.go('software'); } },
  { name: 'shell-chat-pinned', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); } },
  { name: 'shell-side-panel', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); await open(k, issuesRow); } },
  { name: 'shell-side-panel-run', prepare: async (k) => { await k.ask('Why did Morning new-ticket check stop?'); await open(k, 'main .thread [data-act="run"][data-arg="issues"]'); } },
  { name: 'shell-side-panel-approval', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); await open(k, 'main .thread [data-act="run"][data-arg="sw"]'); } },
  { name: 'shell-full-page-back', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); await open(k, issuesRow); await open(k, '#sidepanel [data-act="panelPage"]'); } },
  { name: 'shell-settings-how-it-works', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="setTab"][data-arg="how"]'); } },
  { name: 'mark-unbuilt-home', prepare: async (k) => { await ctl(k, 'markUnbuilt', 'on'); } },
  { name: 'answers-watch-marks', prepare: async (k) => { await k.ask('watch Kubernetes every Monday at 9am and create a Jira ticket'); } },
  { name: 'answers-cross', prepare: async (k) => { await k.ask(CROSS); } },
  { name: 'answers-edit', prepare: async (k) => { await k.ask('Make the morning new-ticket check run on Mondays only'); } },
  { name: 'answers-edit-saved', prepare: async (k) => { await k.ask('Make the morning new-ticket check run on Mondays only'); await open(k, '[data-act="editSave"]'); } },
  { name: 'answers-versions', prepare: async (k) => { await k.ask('Make the morning new-ticket check run on Mondays only'); await open(k, '[data-act="editSave"]'); await k.go('workflows'); await open(k, S.row('issues')); await k.page.evaluate(() => { const h = [...document.querySelectorAll('main h2')].find((x) => x.textContent === 'Versions'); if (h) h.scrollIntoView(); }); } },
  { name: 'answers-status', prepare: async (k) => { await k.ask('which software is behind?'); } },
  { name: 'answers-panel-building', prepare: async (k) => { await k.ask(WEEKLY_SUMMARY); await k.wait(1200); } },
  /* Runs and approvals (ADR 0043, step 3). In the chat the side panel's body scrolls, so a prepare brings its part into view. */
  { name: 'runs-card-stopped', prepare: async (k) => { await k.ask('Why did Weekly closed-ticket summary stop?'); } },
  { name: 'runs-panel-stopped', prepare: async (k) => { await k.ask('Why did Weekly closed-ticket summary stop?'); await open(k, `${lastCard} [data-act="run"][data-arg="nudge"]`); } },
  { name: 'runs-line-waiting', prepare: async (k) => { await k.go('workflows'); await open(k, S.review); await k.page.evaluate(() => window.scrollTo(0, 0)); } },
  /* Held mid-run, with the agents' chat folded, because its typing dots never stop while the run is held. With reduced
     motion a run opens at its end, so Replay the run plays it again step by step. */
  { name: 'runs-line-mid', prepare: async (k) => {
    await k.go('workflows'); await k.page.click(S.retry); await k.settle();
    if (!(await k.page.$('main .line > .st.now'))) { await open(k, 'main [data-act="runDetail"]'); await open(k, 'main [data-act="replay"]'); }
    await k.page.waitForFunction(() => [...document.querySelectorAll('main .line > .st')].findIndex((x) => x.classList.contains('now')) >= 2);
    await k.page.evaluate(() => window.mock.hold());
    if (await k.page.$('main #run-detail')) await open(k, 'main [data-act="runDetail"]');
  } },
  { name: 'runs-approval-panel', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); await open(k, 'main .thread [data-act="run"][data-arg="sw"]'); await inPanel(k, '#sidepanel dl.unchecked'); } },
  { name: 'runs-ask-open', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); await open(k, 'main [data-act="askOpen"][data-arg="sw"]'); } },
  { name: 'runs-ask-panel', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); await open(k, 'main .thread [data-act="run"][data-arg="sw"]'); await open(k, '#sidepanel [data-act="askOpen"][data-arg="sw"]'); await inPanel(k, '#sidepanel .askbox'); } },
  { name: 'runs-asked', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); await open(k, 'main [data-act="askOpen"][data-arg="sw"]'); await k.page.fill('#ask-sw', 'Has the FastAPI change been tested with our login service?'); await open(k, 'main form[data-submit="askSend"] button[type="submit"]'); await ctl(k, 'answerAs', 'sw:0'); await k.page.evaluate(() => document.querySelector('main .asks').scrollIntoView({ block: 'center' })); } },
  { name: 'runs-answer', prepare: async (k) => { await testRunWaiting(k); await k.setUser('bob'); await k.go('home'); await open(k, 'main [data-act="run"][data-arg="conf"]'); await open(k, 'main [data-act="askOpen"][data-arg="conf"]'); await k.page.fill('#ask-conf', 'Should MOCK-31 be in this summary?'); await open(k, 'main form[data-submit="askSend"] button[type="submit"]'); await k.setUser('alice'); await k.go('workflows'); await open(k, 'main [data-act="run"][data-arg="conf"]:has-text("Answer Bob")'); } },
  { name: 'runs-needs-question', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); await open(k, 'main [data-act="askOpen"][data-arg="sw"]'); await k.page.fill('#ask-sw', 'Is this urgent?'); await open(k, 'main form[data-submit="askSend"] button[type="submit"]'); await k.setUser('alice'); await k.go('home'); await testRunWaiting(k); await k.setUser('bob'); await k.go('home'); await open(k, 'main [data-act="run"][data-arg="conf"]'); await open(k, 'main [data-act="askOpen"][data-arg="conf"]'); await k.page.fill('#ask-conf', 'Should MOCK-31 be in this summary?'); await open(k, 'main form[data-submit="askSend"] button[type="submit"]'); await k.setUser('alice'); await k.go('workflows'); } },
  { name: 'runs-decline-reasons', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); await open(k, 'main [data-act="decline"][data-arg="sw"]'); await open(k, 'main [data-act="declinePick"][data-arg="Wrong version"]'); } },
  { name: 'runs-panel-decline-reasons', prepare: async (k) => { await k.ask(CHECK_WORKFLOWS); await open(k, 'main .thread [data-act="run"][data-arg="sw"]'); await open(k, '#sidepanel [data-act="decline"][data-arg="sw"]'); await open(k, '#sidepanel [data-act="declinePick"][data-arg="Not this week"]'); await inPanel(k, '#sidepanel .decide'); } },
  { name: 'runs-declined-run', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await k.page.evaluate(() => window.scrollTo(0, 0)); } },
  { name: 'runs-declined-detail', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await open(k, 'main [data-act="runDetail"]'); } },
  { name: 'runs-declined-panel', prepare: async (k) => { await testRunWaiting(k); await bobDeclines(k, 'conf', 'Something in it is wrong'); await k.setUser('alice'); await k.go('home'); await k.ask('What needs me?'); await open(k, `${lastCard} [data-act="run"][data-arg="conf"]`); } },
  { name: 'runs-declined-needs', prepare: async (k) => { await testRunWaiting(k); await bobDeclines(k, 'conf', 'Something in it is wrong'); await k.setUser('alice'); await k.go('workflows'); } },
  { name: 'runs-declined-teams', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await open(k, S.teams); } },
  { name: 'runs-declined-watchlist', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await k.setUser('alice'); await k.go('software'); await open(k, 'main [data-act="swHist"][data-arg="lg"]'); } },
  /* Step 3 fix pass: each workflow's last run, a question kept on a decided request, both Approvers on a declined access review, and the unbuilt marks. */
  { name: 'runs-workflows-last-run', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await k.setUser('alice'); await k.go('workflows'); await k.page.evaluate(() => document.getElementById('all-h').scrollIntoView()); } },
  { name: 'runs-check-card-declined', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await k.setUser('alice'); await k.go('home'); await k.ask(CHECK_WORKFLOWS); } },
  { name: 'runs-thread-kept', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); await open(k, 'main [data-act="askOpen"][data-arg="sw"]'); await k.page.fill('#ask-sw', 'Is this urgent?'); await open(k, 'main form[data-submit="askSend"] button[type="submit"]'); await open(k, 'main [data-act="decline"][data-arg="sw"]'); await k.page.click('main [data-act="declineYes"][data-arg="sw"]'); await k.waitText(/Declined, nothing was written/); await k.settle(); } },
  { name: 'runs-declined-access', prepare: async (k) => { await ctl(k, 'preview', 'on'); await k.setUser('bob'); await k.go('home'); await open(k, 'main [data-act="run"][data-arg="access"]'); await open(k, 'main [data-act="approve"][data-arg="access"]'); await k.setUser('alice'); await k.go('workflows'); await open(k, 'main [data-act="run"][data-arg="access"]:has-text("Review and decide")'); await open(k, 'main [data-act="decline"][data-arg="access"]'); await open(k, 'main [data-act="declinePick"][data-arg="Someone still needs access"]'); await k.page.click('main [data-act="declineYes"][data-arg="access"]'); await k.waitText(/Declined, nothing was removed/); await k.settle(); } },
  { name: 'runs-mark-approval', prepare: async (k) => { await ctl(k, 'markUnbuilt', 'on'); await k.setUser('bob'); await open(k, S.review); await open(k, 'main [data-act="decline"][data-arg="sw"]'); } },
  /* Roles (ADR 0043, step 4), as Bob, as Alice (an Operator without n8n access) and as Carol (an Operator with it). */
  { name: 'roles-bob-asked-needs', prepare: async (k) => { await k.setUser('bob'); await k.ask('What is waiting for my yes?'); } },
  { name: 'roles-bob-decided', prepare: async (k) => { await bobDeclines(k, 'sw', 'Wrong version'); await k.go('home'); await k.ask('What did I decide before?'); } },
  { name: 'roles-bob-refused', prepare: async (k) => { await k.setUser('bob'); await k.ask('Make the morning new-ticket check run on Mondays only'); } },
  { name: 'roles-bob-decide', prepare: async (k) => { await k.setUser('bob'); await k.ask('approve the upgrade tickets'); } },
  { name: 'roles-bob-abilities', prepare: async (k) => { await k.setUser('bob'); await open(k, 'main [data-act="abil"]'); } },
  { name: 'roles-bob-panel', prepare: async (k) => { await k.setUser('bob'); await k.ask('What is waiting for my yes?'); await open(k, `${lastCard} [data-act="run"][data-arg="sw"]`); } },
  { name: 'roles-bob-workflows', prepare: async (k) => { await k.setUser('bob'); await k.go('workflows'); } },
  { name: 'roles-bob-workflow-page', prepare: async (k) => { await k.setUser('bob'); await k.go('workflows'); await open(k, S.row('issues')); } },
  { name: 'roles-bob-watchlist', prepare: async (k) => { await k.setUser('bob'); await k.go('software'); } },
  { name: 'roles-bob-offline', prepare: async (k) => { await k.setUser('bob'); await ctl(k, 'modelOn', 'off'); } },
  { name: 'roles-alice-n8n-refused', prepare: async (k) => { await ctl(k, 'preview', 'on'); await k.ask('open the morning new-ticket check in n8n'); } },
  { name: 'roles-alice-build-planned', prepare: async (k) => { await ctl(k, 'preview', 'on'); await k.ask(WEEKLY_SUMMARY); await k.wait(1800); } },
  { name: 'roles-alice-n8n-change', prepare: async (k) => { await ctl(k, 'preview', 'on'); await k.go('workflows'); await open(k, S.row('issues')); await ctl(k, 'n8nChange', 'issues'); } },
  { name: 'roles-carol-home', prepare: async (k) => { await k.setUser('carol'); } },
  { name: 'roles-carol-build-n8n', prepare: async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); await k.ask(WEEKLY_SUMMARY); await k.wait(1800); } },
  { name: 'roles-carol-workflow-n8n', prepare: async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); await k.go('workflows'); await open(k, S.row('issues')); await open(k, 'main details.tech > summary'); await k.page.evaluate(() => { const h = [...document.querySelectorAll('main h3')].find((x) => /In n8n/.test(x.textContent)); if (h) h.scrollIntoView(); }); } },
  { name: 'roles-carol-menu-n8n', prepare: async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); await k.go('workflows'); await open(k, S.row('issues')); await open(k, S.more); } },
  { name: 'roles-carol-n8n-ask', prepare: async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); await k.ask('open n8n'); } },
  { name: 'roles-carol-n8n-dialog', prepare: async (k) => { await k.setUser('carol'); await ctl(k, 'preview', 'on'); await k.ask('open the morning new-ticket check in n8n'); await open(k, `${lastCard} [data-act="n8nAsk"]`); } },
  { name: 'roles-settings-people', prepare: async (k) => { await ctl(k, 'preview', 'on'); await open(k, '.hdr [data-act="go"][data-arg="settings"]'); await open(k, '[data-act="setTab"][data-arg="people"]'); } },
  /* Step 4 fix pass. */
  { name: 'fix-bob-people', prepare: async (k) => { await k.setUser('bob'); await open(k, '.hdr [data-act="go"][data-arg="settings"]'); await open(k, '[data-act="setTab"][data-arg="people"]'); } },
  { name: 'fix-bob-declines', prepare: async (k) => { await k.setUser('bob'); await k.ask('did I decline anything?'); } },
  { name: 'fix-edit-tickets', prepare: async (k) => { await turnOnWeekly(k); await k.ask('Make the friday closed ticket summary run every day'); } },
  { name: 'fix-gitlab', prepare: async (k) => { await k.ask('Every Monday at 9am, sum up the closed tickets from GitLab in MOCK'); } },
  { name: 'fix-day-choice', prepare: async (k) => { await k.ask('Every Monday and Friday at 9am, sum up the closed tickets in MOCK'); await open(k, `${lastCard} [data-act="answer"][data-arg="day:Monday"]`); } },
  { name: 'fix-open-software', prepare: async (k) => { await k.ask('Open Redis on the Software page'); } },
  { name: 'fix-run-log', prepare: async (k) => { await k.go('workflows'); await open(k, S.row('issues')); await open(k, 'main [data-act="watch"][data-arg="issues"]'); await k.waitText(/Safe to retry/); if (!(await k.page.$('#run-detail'))) await open(k, 'main [data-act="runDetail"]'); } },
];

/* The rail replaced the header tabs (ADR 0043). The Agent library is now Settings, How it works. */
const menu = (width, name) => (name === 'agents' ? '.hdr [data-act="go"][data-arg="settings"]' : `.rail-a[data-arg="${name}"]`);

module.exports = {
  version: 'v4',
  menu,
  scenarios,
  screens,
  ctl,
  /* The keyboard check in quality.cjs: the control a keyboard user must reach on Home. */
  keyboard: { operatorTarget: '[data-ask]', approverTarget: '[data-act="run"][data-arg="sw"]' },
  /* Which controls open the Teams drawer and the test controls, so shots and quality can leave them out. */
  hide: '.testctl, .toast',
};
