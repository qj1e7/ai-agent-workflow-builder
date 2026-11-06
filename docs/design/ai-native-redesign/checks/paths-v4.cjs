/* Paths for version 4, docs/design/ai-native-redesign/prototype.html.
   Copied from paths-v3.cjs. The ids are the same, each doing the same user task the version 4 way, with the same
   counting rules and the same decision tags. A scenario whose task changed on purpose carries `changed: 'why'`. */

const WEEKLY_SUMMARY = 'every Friday, sum up the tickets we closed this week';
const EMAIL = 'email me a list of open bugs every Monday';

/* Selectors */
const S = {
  ask: '[data-ask]',
  example: (i) => `main [data-act="example"][data-arg="${i}"]`,
  start: (i) => `main .thread [data-act="say"] >> nth=${i}`,
  time: '#sched-time',
  project: '#fix-project',
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

/* The same set-up as a user would do it, without counting it. */
async function turnOnWeekly(k) {
  await k.ask(WEEKLY_SUMMARY);
  await k.page.selectOption(S.project, 'MOCK');
  await k.settle();
  await k.page.fill(S.time, '17:00');
  await k.settle();
  await k.page.click(S.turnOn);
  await k.settle(600);
}

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
  await t.expectText('Day one Home asks what the team does again and again', /again and again/);
  await t.ask(WEEKLY_SUMMARY, 'every Friday, sum up the tickets we closed this week');
  const left = await t.page.innerText('main');
  const asks = Number((left.match(/(\d+) choices? left/) || [0, 0])[1]);
  t.metric('plannerQuestions', asks);
  await t.expect('The Planner asks back for when it runs and the Jira project', left, /2 choices left: when it runs and the Jira project/);
  await t.select(S.project, 'MOCK', 'Choose the Jira project', { decision: true });
  await t.field(S.time, '17:00', 'Choose the time', { decision: true });
  await t.expectText('Nothing is unclear before turning on', /Nothing is unclear\. One yes turns it on\./);
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Friday closed ticket summary is on/);
}, [1280, 390]);

/* B. Experienced Operator, a normal week. Through Workflows, as in version 3. B-home does it from Home. */
add('B', 'Experienced Operator finds what needs attention and fixes the stopped Morning new-ticket check', async (t) => {
  await t.menu('workflows', 'Open Workflows');
  await t.expectText('Needs you lists four things', /Needs you\s+4/);
  await t.expectText('The stopped Morning new-ticket check is listed with what happened and a fix', /Morning new-ticket check stopped[\s\S]*Jira didn’t answer at 8:00[\s\S]*A retry is safe[\s\S]*Retry the run/);
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
  await t.click(S.example(2), 'Tap Set up another workflow', { reply: true });
  await t.click(S.start(0), 'Tap the first starting point', { reply: true });
  await t.select(S.project, 'MOCK', 'Choose the Jira project', { decision: true });
  await t.field(S.time, '17:00', 'Choose the time', { decision: true });
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.click(S.testRun, 'Do a test run', { until: /another Approver must decide/ });
  await t.expectText('The page says Alice cannot approve her own run', /You set this up and started this run, so another Approver must decide\. Nobody approves their own work\./);
  await t.expectCount('There is no Approve button for her', '[data-act="approve"][data-arg="conf"]', 0);
}, [1280], { changed: 'Normal-week Home suggests from state (spec 5.1). Set-up examples sit behind “Set up another workflow”, one tap more.' });

/* D. Unsupported request. */
add('D', 'An Operator asks to email a weekly list, and the limit is explained with an alternative', async (t) => {
  await t.ask(EMAIL, 'email me a list of open bugs every Monday');
  await t.expectText('The Planner says it cannot send email', /I can’t send email\. Email and Slack aren’t connected to the platform/);
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
  await t.click(S.more, 'More actions');
  await t.click(S.pick('pause', 'issues'), 'Pause', { decision: true });
  await t.expectText('The workflow is paused', /Paused\. Morning new-ticket check won’t run until you resume it/, S.toast);
  await t.expectCount('A Resume button replaces Pause', 'main [data-act="resume"]', 1);
  await t.click('main [data-act="go"][data-arg="workflows"]', 'Back to Workflows');
  await t.click(S.row('nudge'), 'Open Weekly closed-ticket summary');
  await t.click(S.more, 'More actions');
  await t.click(S.pick('askDelete', 'nudge'), 'Delete');
  await t.expectText('A confirmation asks first', /Delete Weekly closed-ticket summary\?[\s\S]*Its past runs and their records stay/, '.dialog');
  await t.click('[data-act="confirmDelete"]', 'Delete workflow', { decision: true });
  await t.expectText('It is deleted, with Undo', /Deleted Weekly closed-ticket summary\.\s*Undo/, S.toast);
  await t.expectCount('It is gone from Workflows', 'main [data-act="workflow"][data-arg="nudge"]', 0);
}, [1280], { changed: 'Pause and Delete moved into the More actions menu (spec 9), one tap more each.' });

/* The fifteen tasks in 03b section 6. */
const T = (n, title, run, extra) => add(`T${n}`, title, run, [1280], extra);

T(1, 'Set up a workflow from example 1: example, time, Jira project, Turn it on', async (t) => {
  await t.click(S.example(2), 'Tap Set up another workflow', { reply: true });
  await t.click(S.start(0), 'Tap the first starting point', { reply: true });
  await t.select(S.project, 'MOCK', 'Choose the Jira project', { decision: true });
  await t.field(S.time, '17:00', 'Choose the time', { decision: true });
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Monday new ticket comparison is on/);
}, { changed: 'Normal-week Home suggests from state. The examples sit behind “Set up another workflow” (spec 5.1).' });

T(2, 'Set up a typed workflow with every part stated: type, Enter, Turn it on', async (t) => {
  await t.ask('Every Friday at 17:00, sum up the tickets we closed this week in project MOCK', 'a request with every part stated');
  await t.expectText('Nothing is unclear', /Nothing is unclear\. One yes turns it on\./);
  await t.click(S.turnOn, 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /is on\./);
}, { changed: 'The v3 request needs a ticket’s update date, which the Jira tool can’t see (UX audit X2), so v4 answers “Part I can do”. The typed request is one the tools can do.' });

T(3, 'Do a test run after turning one on', async (t) => {
  await t.setup(turnOnWeekly);
  await t.click(S.testRun, 'Do a test run', { until: /Who asked[\s\S]*Alice started a test run/ });
  await t.expectText('A test run is under way', /Test run[\s\S]*Alice started a test run/);
});

T(4, 'Add software from Home with example 3: example, Looks right, Start from the newest, Add React', async (t) => {
  await t.click(S.example(2), 'Tap Set up another workflow', { reply: true });
  await t.click(`main .thread [data-act="say"][data-arg="Keep track of the React version"]`, 'Tap Keep track of the React version', { reply: true });
  await t.click('[data-act="repoOk"]', 'Looks right', { decision: true });
  await t.click('[data-act="verNewest"]', 'Not sure? Start from the newest');
  await t.click('[data-act="watchAdd"]', 'Add React', { decision: true });
  await t.expectText('React is on the Software watchlist', /React is on the Software watchlist/);
}, { changed: 'The React example sits behind “Set up another workflow” on a normal week (spec 5.1).' });

T(5, 'Add software on the Software watchlist page', async (t) => {
  await t.menu('software', 'Open Software watchlist');
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
  await t.click(S.more, 'More actions');
  await t.click(S.pick('pause', 'issues'), 'Pause', { decision: true });
  await t.expectText('The workflow is paused', /Paused\. Morning new-ticket check won’t run until you resume it/, S.toast);
}, { changed: 'The quarterly access review is Planned and hidden by default (I2), so another workflow is paused. Pause is in the More actions menu (spec 9).' });

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

T(14, 'Change an agent in plain English: Agent library, Details and changes, chip, Suggest a change, Save', async (t) => {
  await t.menu('agents', 'Open Agent library');
  await t.click('[data-act="libTab"][data-arg="agents"]', 'Open the Agents tab');
  await t.click('[data-act="agent"][data-arg="writer"]:has-text("Details and changes")', 'Ticket writer: Details and changes');
  await t.click('[data-act="agentChip"]', 'Pick a suggested change');
  await t.click('[data-act="agentSuggest"]', 'Suggest a change');
  await t.click('[data-act="agentSave"]', 'Save as version 2', { decision: true });
  await t.expectText('Saved as version 2', /Saved as version 2\. Ticket writer uses it from the next run/, S.toast);
}, { changed: 'The Agent library opens on “What it can do” (spec 12), so the agents are one tab away.' });

T(15, 'Ask the team for a new system, after a "can’t" answer', async (t) => {
  await t.setup((k) => k.ask(EMAIL));
  await t.click('[data-act="teamReq"]:has-text("Ask the team")', 'Ask the team', { decision: true });
  await t.expectText('The request is sent to the team', /Sent to the team\. You can follow it on Tools, in the Agent library\./, S.toast);
});

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
  await t.expectText('Home lists the stopped workflow first, with its fix', /Needs you\s+4\s+Morning new-ticket check stopped\s+Jira didn’t answer at 8:00\.\s+Retry the run/);
  await t.click(S.retry, 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The retry finished', retriedText);
  await t.setup((k) => k.go('home'));
  await t.expectText('Home now has three things', /3 things need you/);
  await t.expect('The stopped row is gone from Home', t.page.innerText('main'), (v) => !/Morning new-ticket check stopped/.test(v));
}, [1280, 390]);

add('ASK-status', '“Check my workflows” from the suggestions', async (t) => {
  await t.click(S.example(0), 'Tap Check my workflows', { reply: true });
  await t.expectText('The Planner sums up every workflow', /You have 3 workflows\. 2 stopped and 1 is waiting for a yes\./, 'main .thread');
  await t.expectCount('One row per workflow', 'main .thread [data-act="workflow"]', 3);
  await t.expectText('Each row has its status, next run and one action', /Morning new-ticket check\s+Stopped\s+Next run[^\n]*\s+Retry the run[\s\S]*Keep our software up to date\s+Waiting for a yes\s+Next run[^\n]*\s+Review and decide/, 'main .thread');
}, [1280, 390]);

add('ASK-why', '“Why did Morning new-ticket check stop?” ending in a retry from the answer', async (t) => {
  await t.click(S.example(1), 'Tap Why did Morning new-ticket check stop?', { reply: true });
  await t.expectText('The four answers', /What happened[\s\S]*What was affected[\s\S]*Can it be fixed safely[\s\S]*What to do/, 'main .thread');
  await t.click('main .thread [data-act="retryIssues"]', 'Retry the run', { decision: true, until: retriedText });
  await t.expectText('The retry finished', retriedText);
}, [1280]);

add('ASK-needs', '“What needs me?”', async (t) => {
  await t.ask('What needs me?');
  await t.expectText('The Planner counts what needs her', /4 things need you\./, 'main .thread');
  await t.expectCount('The Needs you rows are in the answer', 'main .thread .needs-row, main .thread [data-act="retryIssues"], main .thread [data-act="report"], main .thread [data-act="run"][data-arg="sw"], main .thread [data-act="setGo"]', (n) => n >= 4);
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
  await t.menu('software', 'Open Software watchlist');
  await t.expectText('Planned sources are tagged', /Security advisories\s+Planned/i);
}, [1280]);

/* Keyboard only: no mouse. Tab, Shift+Tab, Enter, Space, arrows, Escape, typing. */
add('KEYS-A', 'Scenario A with the keyboard only', async (t) => {
  await t.setup(async (k) => { await k.setDay('one'); await focusTop(k); });
  await t.press('Tab', 'Tab to Skip to main content');
  await t.press('Enter', 'Skip to main content');
  await tabTo(t, '[data-ask]', 'the Planner box');
  await t.field(':focus', WEEKLY_SUMMARY, 'Type the request');
  await t.press('Enter', 'Send', { reply: true });
  await tabTo(t, '#fix-project', 'the Jira project choice');
  await t.press('m', 'Type M to choose MOCK', { decision: true });
  await t.expect('The project is MOCK', t.page.$eval('#fix-project', (s) => s.value), 'MOCK');
  await tabTo(t, '#sched-time', 'the time');
  await t.field(':focus', '17:00', 'Type the time', { decision: true });
  await tabTo(t, '[data-act="turnOn"]', 'Turn it on');
  await t.press('Enter', 'Turn it on', { decision: true });
  await t.expectText('The workflow is on', /Friday closed ticket summary is on/);
}, [1280]);

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
  { name: 'run-stopped', prepare: async (k) => { await k.go('workflows'); await open(k, S.seeRun); } },
  { name: 'run-approval', prepare: async (k) => { await k.setUser('bob'); await open(k, S.review); } },
  { name: 'software', prepare: async (k) => { await k.go('software'); } },
  { name: 'agent-library', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="libTab"][data-arg="agents"]'); } },
  { name: 'agent-library-tools', prepare: async (k) => { await k.go('agents'); await open(k, '[data-act="libTab"][data-arg="tools"]'); } },
  { name: 'settings-connections', prepare: async (k) => { await open(k, '.hdr [data-act="go"][data-arg="settings"]'); await open(k, '[data-act="setTab"][data-arg="connections"]'); } },
  { name: 'teams-drawer', prepare: async (k) => { await open(k, S.teams); } },
  { name: 'drafts', prepare: async (k) => { await k.ask(WEEKLY_SUMMARY); await open(k, '[data-act="newChat"]'); await k.go('workflows'); } },
  { name: 'home-needs-you', prepare: async (k) => { await k.page.evaluate(() => { const h = [...document.querySelectorAll('main h2')].find((x) => /Needs you/.test(x.textContent)); if (h) h.scrollIntoView(); }); } },
  { name: 'planner-check-workflows', prepare: async (k) => { await open(k, S.example(0)); } },
  { name: 'planner-why-stopped', prepare: async (k) => { await open(k, S.example(1)); } },
  { name: 'workflow-more-menu', prepare: async (k) => { await k.go('workflows'); await open(k, S.row('issues')); await open(k, S.more); } },
  { name: 'run-detailed-activity', prepare: async (k) => { await k.go('workflows'); await open(k, S.seeRun); await open(k, 'main [data-act="runDetail"]'); } },
  { name: 'software-attention', prepare: async (k) => { await k.go('software'); await k.page.evaluate(() => { const h = document.getElementById('sw-attn-h'); if (h) h.scrollIntoView(); }); } },
  { name: 'library-what-it-can-do', prepare: async (k) => { await k.go('agents'); } },
  { name: 'offline-home', prepare: async (k) => { await ctl(k, 'modelOn', 'off'); } },
  { name: 'preview-software', prepare: async (k) => { await ctl(k, 'preview', 'on'); await k.go('software'); } },
  { name: 'mark-unbuilt-home', prepare: async (k) => { await ctl(k, 'markUnbuilt', 'on'); } },
];

module.exports = {
  version: 'v4',
  scenarios,
  screens,
  ctl,
  /* The keyboard check in quality.cjs: the control a keyboard user must reach on Home. */
  keyboard: { operatorTarget: '[data-ask]', approverTarget: '[data-act="run"][data-arg="sw"]' },
  /* Which controls open the Teams drawer and the test controls, so shots and quality can leave them out. */
  hide: '.testctl, .toast',
};
