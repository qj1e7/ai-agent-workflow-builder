/* Gate checks for the P0 slice of the AI-native redesign (correctness and trust).
   Usage: node docs/design/ai-native-redesign/checks/gates-p0.cjs <prototype.html>
   Prints one line per named check and exits non-zero on any failure. One control check is seeded to fail, to prove the
   gate can fail; it is reported as an expected failure and does not count. */
const path = require('path');
const fs = require('fs');
const assert = require('assert');
const { execFileSync } = require('child_process');

const file = path.resolve(process.argv[2] || path.join(__dirname, '..', 'prototype.html'));
const here = path.resolve(__dirname, '..', '..', '..', '..');
const common = (() => { try { return path.dirname(path.resolve(here, execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: here }).toString().trim())); } catch (e) { return here; } })();
const { chromium } = require(require.resolve('playwright', { paths: [path.join(here, 'portal'), path.join(common, 'portal')] }));
const url = `file://${file}`;
const source = fs.readFileSync(file, 'utf8');

const NEW_TOOL = 'I can’t add that yet. The team decides on new tools.';
const EX_SUMMARY = 'Every Friday, sum up the tickets we closed this week';
const EX_COMPARE = 'Every Monday, compare last week’s new tickets with the week before';

const results = [];
const consoleErrors = [];
const record = (name, err, expectedFail) => {
  const ok = !err;
  const status = expectedFail ? (ok ? 'FAIL' : 'EXPECTED-FAIL') : ok ? 'PASS' : 'FAIL';
  results.push({ name, status });
  console.log(`${status.padEnd(13)} ${name}${err ? `: ${String(err.message || err).split('\n')[0]}` : ''}${expectedFail && ok ? ': the seeded control passed, so the gate cannot fail' : ''}`);
};

async function session(browser, width, body) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce', colorScheme: 'light' });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror @${width}: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`console @${width}: ${m.text()}`); });
  await page.goto(url);
  await page.waitForTimeout(250);
  const t = {
    page,
    width,
    wait: (ms) => page.waitForTimeout(ms),
    text: () => page.innerText('main'),
    all: () => page.innerText('body'),
    has: async (sel) => (await page.$(sel)) !== null,
    count: (sel) => page.$$eval(sel, (els) => els.length).catch(() => 0),
    click: async (sel) => { await page.click(sel); await page.waitForTimeout(220); },
    go: async (tab) => { await page.click(`${width > 900 ? '.nav-a' : '.tab'}[data-arg="${tab}"]`); await page.waitForTimeout(260); },
    openTest: async () => { if (!(await page.$('.testctl-panel'))) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    closeTest: async () => { if (await page.$('.testctl-panel')) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    ctl: async (act, arg) => { await t.openTest(); await page.click(`.testctl [data-act="${act}"][data-arg="${arg}"]`); await page.waitForTimeout(260); await t.closeTest(); },
    sim: async (label) => { await t.openTest(); await page.$eval(`.testctl button:has-text("${label}")`, (b) => b.click()); await page.waitForTimeout(260); await t.closeTest(); },
    ask: async (text) => { await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await page.waitForTimeout(700); },
    reply: () => page.locator('.thread [data-say]').last().innerText(),
    card: () => page.locator('.thread .pcard').last().innerText(),
    settings: async (tab) => { await page.click('.hdr [data-act="go"][data-arg="settings"]'); await page.waitForTimeout(220); await page.click(`[data-act="setTab"][data-arg="${tab}"]`); await page.waitForTimeout(220); },
    teams: async () => { await page.click('.hdr [data-act="teams"]'); await page.waitForTimeout(260); return page.innerText('.drawer'); },
    closeTeams: async () => { await page.keyboard.press('Escape'); await page.waitForTimeout(200); },
    /* Ask the Planner for a workflow, fill the card's one project and time, and turn it on. The project goes first:
       the time picker opens by itself only once the schedule is the one thing left (P1a, spec 7.1). */
    turnOn: async (text) => {
      await t.ask(text);
      if (await page.$('#fix-project')) { await page.selectOption('#fix-project', 'MOCK'); await page.waitForTimeout(220); }
      if (await page.$('#sched-time')) { await page.fill('#sched-time', '09:00'); await page.click('[data-act="whenDone"]'); await page.waitForTimeout(220); }
      await page.click('[data-act="turnOn"]');
      await page.waitForTimeout(260);
    },
  };
  try { await body(t); } finally { await page.close(); }
}

const checks = [];
const check = (name, fn, opts = {}) => checks.push({ name, fn, ...opts });

/* Every sentence that mentions Teams may only be about the approval request. */
const TEAMS_ALLOWED = /\b(yes|approv|asked|ask |request|decide|decision|nothing (else )?(is|was) posted|practice copy|open in|reaches the real|teams answered|signed in|carries approval)/i;
const TEAMS_SUSPECT = /\b(post|posts|posted|posting|send|sends|sent|sending|message|messages|notif\w*|remind\w*)\b/i;
/* The registry's own "Not yet" line names the planned capability; it promises nothing. */
const NOT_YET_LINES = ['Post messages in Teams'];
function teamsPromises(text) {
  return text.split(/(?<=[.!?])\s+|\n+/).filter((s) => /\bTeams\b/.test(s) && TEAMS_SUSPECT.test(s) && !TEAMS_ALLOWED.test(s) && !NOT_YET_LINES.includes(s.trim()));
}

/* I1: the visible text of every screen in default mode, including the Teams drawer, the support case and AI usage. */
async function sweep(t) {
  const seen = [];
  const grab = async (label) => seen.push([label, await t.text()]);
  await t.ctl('day', 'one'); await grab('day one');
  await t.ctl('day', 'week');
  await t.click('[data-act="abil"]'); await grab('home abilities');
  await t.go('workflows'); await grab('workflows');
  for (const id of ['issues', 'nudge']) { await t.click(`[data-act="workflow"][data-arg="${id}"]`); await grab(`workflow ${id}`); await t.click(`[data-act="run"][data-arg="${id}"], [data-act="watch"][data-arg="${id}"]`); await t.wait(300); await grab(`run ${id}`); await t.go('workflows'); }
  await t.click('[data-act="report"]'); await t.wait(200); seen.push(['report dialog', await t.page.innerText('.dialog')]);
  await t.click('[data-act="sendReport"]'); await t.wait(200); seen.push(['report sent', await t.page.innerText('.dialog')]);
  await t.page.keyboard.press('Escape'); await t.wait(200); await grab('workflows following up');
  await t.go('software'); await grab('watchlist');
  await t.click('[data-act="watch"][data-arg="sw"], [data-act="run"][data-arg="sw"]'); await t.wait(300); await grab('run sw');
  await t.go('agents'); await grab('agents');
  await t.click('[data-act="libTab"][data-arg="tools"]'); await grab('tools');
  await t.click('[data-act="toolOpen"][data-arg="jiraCreate"]'); seen.push(['tool dialog', await t.page.innerText('.dialog')]); await t.page.keyboard.press('Escape'); await t.wait(150);
  for (const tab of ['model', 'connections', 'people', 'usage']) { await t.settings(tab); await grab(`settings ${tab}`); }
  seen.push(['teams drawer', await t.teams()]); await t.closeTeams();
  await t.ctl('user', 'bob'); await grab('bob home'); seen.push(['bob teams drawer', await t.teams()]); await t.closeTeams();
  return seen;
}

check('no-long-dashes', () => {
  const bad = source.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => /[—–]/.test(l)).map(([i]) => i);
  assert.deepStrictEqual(bad, [], `long dashes on lines ${bad.join(', ')}`);
});
check('i1-source-no-teams-promises', () => {
  const stale = [/Teams message/, /had a message in Teams/, /gets a Teams/, /requests and messages/, /Send Teams messages/, /asks their owners in Teams/, /Send the messages in Teams/, /message in Teams\b(?! that| when)/];
  const hits = stale.filter((re) => re.test(source)).map(String);
  assert.deepStrictEqual(hits, [], `source still carries ${hits.join(' ')}`);
});
check('i7-stale-text-gone', () => {
  const hits = [/follow it on Home/, /Check what I understood/].filter((re) => re.test(source)).map(String);
  assert.deepStrictEqual(hits, [], `source still carries ${hits.join(' ')}`);
});

for (const width of [1280, 390]) {
  check(`i1-no-teams-promises@${width}`, async (browser) => session(browser, width, async (t) => {
    const seen = await sweep(t);
    const bad = seen.flatMap(([label, text]) => teamsPromises(text).map((s) => `[${label}] ${s.trim()}`));
    assert.deepStrictEqual(bad, [], `Teams promises: ${bad.join(' | ')}`);
    assert(seen.length >= 20, `screens swept: ${seen.length}`);
  }));
}

check('i2-samples-use-todays-tools', async (browser) => session(browser, 1280, async (t) => {
  const texts = [];
  await t.go('workflows'); texts.push(await t.text());
  for (const id of ['issues', 'nudge']) { await t.click(`[data-act="workflow"][data-arg="${id}"]`); texts.push(await t.text()); await t.go('workflows'); }
  await t.go('agents'); texts.push(await t.text());
  await t.click('[data-act="libTab"][data-arg="tools"]'); texts.push(await t.text());
  const bad = texts.flatMap((x) => x.match(/GitHub issues|bug reports? on|Entra|GitLab|admin tools|Issue reader|Access checker|Message writer|Post in Teams|langserve/gi) || []);
  assert.deepStrictEqual(bad, [], `planned systems in default samples: ${bad.join(', ')}`);
  const wf = texts[0];
  for (const name of ['Morning new-ticket check', 'Weekly closed-ticket summary', 'Keep our software up to date']) assert(wf.includes(name), `Workflows lists ${name}`);
  assert(!wf.includes('Quarterly access review'), 'access review hidden by default');
}));

check('i3-one-answer-new-tool', async (browser) => session(browser, 1280, async (t) => {
  await t.ask('Put new tickets in the Platform component');
  const home = await t.reply();
  assert(home.includes(NEW_TOOL), `Home reply: ${home}`);
  assert((await t.card()).includes('Ask the team'), 'Home card offers Ask the team');
  await t.go('agents'); await t.click('[data-act="libTab"][data-arg="tools"]');
  await t.page.fill('#tool-ask', 'Set a component on new Jira tickets'); await t.click('[data-act="toolAskGo"]');
  const tools = await t.page.innerText('#tool-reply');
  assert(tools.includes(NEW_TOOL), `Tools reply: ${tools}`);
  assert(tools.includes('Ask the team'), 'Tools reply offers Ask the team');
  assert(!/draft/i.test(tools), `Tools reply offers no draft: ${tools}`);
  await t.click('[data-act="libTab"][data-arg="agents"]');
  await t.click('[data-act="agent"][data-arg="writer"]');
  await t.page.fill('#agent-text', 'Put tickets in the Platform component'); await t.click('[data-act="agentSuggest"]');
  const agent = await t.page.innerText('#agent-proposal');
  assert(agent.includes(NEW_TOOL), `Agent reply: ${agent}`);
  assert(agent.includes('Ask the team'), 'Agent reply offers Ask the team');
}));

check('i4-todays-rule-everywhere', async (browser) => session(browser, 1280, async (t) => {
  await t.ask(EX_SUMMARY);
  assert((await t.card()).includes('Any Approver on your team except you'), 'set-up card uses today’s rule');
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="issues"]');
  const wf = await t.text();
  assert(wf.includes('Any Approver except Alice'), `workflow page: ${wf.match(/Who approves[^\n]*\n[^\n]*/)}`);
  assert(!/backup|Change who approves|stops waiting|before the next run/i.test(wf), 'no ADR 0024 wording on the workflow page');
  await t.go('software');
  const sw = await t.text();
  assert(sw.includes('Who approves: Any Approver except Carol'), 'watchlist uses today’s rule');
  assert(!/backup|Change who approves/i.test(sw), 'no ADR 0024 wording on the watchlist');
  await t.go('home'); await t.ask('Keep track of the React version');
  assert((await t.card()).includes('Any Approver except Carol'), 'watch card uses today’s rule');
}));

check('i5-day-one-model-and-keys', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('day', 'one');
  assert.strictEqual(await t.count('.hdr .badge'), 0, 'no warning counts on day one');
  const home = await t.text();
  assert(!home.includes('Needs you'), 'no Needs you on day one');
  assert(home.includes('I can'), 'abilities listed on day one');
  await t.settings('model');
  assert((await t.text()).includes('Connected'), 'day one has a connected model');
  await t.settings('connections');
  assert(!/in \d+ days/.test(await t.text()), 'day one keys are fresh');
}));

check('i6-new-agent-drafted', async (browser) => session(browser, 1280, async (t) => {
  await t.ask(EX_COMPARE);
  /* The agents sit under How this workflow works, collapsed (P1a, spec 7.1). */
  await t.click('.thread .pcard details.how summary');
  const card = await t.card();
  assert(card.includes('Week-on-week writer'), `card names the new agent: ${card}`);
  assert(card.includes('New agent, saved to the Agent library when you turn this on'), 'card marks the new agent');
  await t.page.selectOption('#fix-project', 'MOCK'); await t.wait(200);
  await t.page.fill('#sched-time', '09:00'); await t.click('[data-act="whenDone"]');
  await t.click('[data-act="turnOn"]');
  await t.go('agents');
  assert((await t.text()).includes('Week-on-week writer'), 'Agent library lists the new agent after Turn it on');
}));

check('i8-one-count', async (browser) => session(browser, 1280, async (t) => {
  await t.ask(EX_SUMMARY);
  const say = await t.reply();
  assert(!/\d+ more answers|one more answer|more answer/i.test(say), `reply carries no count: ${say}`);
  assert.strictEqual(await t.count('.thread .pcard-f .left'), 1, 'the card footer is the one count');
  const footer = await t.page.locator('.thread .pcard-f .left').innerText();
  assert(/choices? left/.test(footer), footer);
}));

check('i9-watchlist-github-only', async (browser) => session(browser, 1280, async (t) => {
  await t.go('software');
  const text = await t.text();
  const bad = text.match(/Maven Central|PyPI|NuGet|Docker Hub|vulnerab|OSV|NVD|CISA|endoflife|Security risk|Support ending/gi) || [];
  assert.deepStrictEqual(bad, [], `ADR 0025 sources shown by default: ${bad.join(', ')}`);
  assert(text.includes('GitHub releases (working)'), 'source states from the registry');
  await t.ctl('preview', 'on');
  const on = await t.text();
  assert(on.includes('Security risks'), 'preview shows the security findings');
  assert((await t.count('.tag.planned')) > 0, 'findings are tagged Planned');
}));

check('preview-off-hides-planned', async (browser) => session(browser, 1280, async (t) => {
  assert.strictEqual(await t.count('.tag.planned'), 0, 'no Planned tags on Home');
  await t.go('workflows'); assert(!(await t.text()).includes('Quarterly access review'), 'access review hidden');
  await t.go('agents'); const ag = await t.text(); assert(!/Vulnerability checker|Message writer|Issue reader|Access checker/.test(ag), 'planned agents hidden');
  await t.click('[data-act="libTab"][data-arg="tools"]'); const tl = await t.text(); assert(!/Post in Teams|package registries|Change someone/.test(tl), 'planned tools hidden');
  assert(!/draft/i.test(tl), 'tool drafting hidden');
  await t.go('software'); assert.strictEqual(await t.count('.tag.planned'), 0, 'no Planned tags on the watchlist');
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="issues"]'); assert(!(await t.text()).includes('Change who approves'), 'named Approvers hidden');
}));

check('preview-on-tags-planned', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('preview', 'on');
  await t.go('workflows');
  assert((await t.page.locator('.wf-row:has-text("Quarterly access review") .tag.planned').count()) === 1, 'access review row tagged');
  await t.click('[data-act="workflow"][data-arg="issues"]');
  assert((await t.page.locator('[data-act="editAppr"] .tag.planned').count()) === 1, 'Change who approves tagged');
  assert(/with .* as backup/.test(await t.text()), 'named Approvers shown');
  await t.go('agents'); assert((await t.page.locator('.agent-lg:has-text("Vulnerability checker") .tag.planned').count()) === 1, 'planned agent tagged');
  await t.click('[data-act="libTab"][data-arg="tools"]'); assert((await t.page.locator('.tool-row:has-text("Post in Teams") .tag.planned').count()) === 1, 'planned tool tagged');
  await t.go('software'); assert((await t.page.locator('section:has-text("Security risks") .tag.planned').count()) >= 1, 'security findings tagged');
}));

check('two-approvers-access-review', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('preview', 'on');
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="access"]');
  const text = await t.text();
  assert(/First Bob.*Then Alice/.test(text), `two Approvers in turn: ${text.match(/Who approves[^\n]*\n[^\n]*/)}`);
  assert(text.includes('2 Approvers, one after the other'), 'plan says two Approvers');
}));

check('teams-drawer-no-approve', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('user', 'bob');
  const drawer = await t.teams();
  assert.strictEqual(await t.page.locator('.drawer button:has-text("Approve")').count(), 0, 'no Approve in Teams');
  assert.strictEqual(await t.page.locator('.drawer button:has-text("Decline")').count(), 0, 'no Decline in Teams');
  assert(drawer.includes('Open in AI Workflow Builder'), 'one Open button');
  for (const part of ['Who can decide', 'Changes', 'Found', 'set up by Carol']) assert(drawer.includes(part), `card has ${part}`);
  await t.click('.drawer [data-act="run"][data-arg="sw"]');
  await t.click('[data-act="approve"][data-arg="sw"]');
  const after = await t.teams();
  assert(/Approved by Bob at \d+:\d\d today/.test(after), `state after decision: ${after.match(/Approved[^\n]*/)}`);
}));

check('control-teams-approve-exists', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('user', 'bob'); await t.teams();
  assert.strictEqual(await t.page.locator('.drawer button:has-text("Approve")').count(), 1, 'seeded control: an Approve button in Teams');
}), { expectedFail: true });

check('self-approval-blocked', async (browser) => session(browser, 1280, async (t) => {
  await t.turnOn(EX_SUMMARY);
  await t.click('[data-act="testRun"]'); await t.wait(400);
  const run = await t.text();
  assert.strictEqual(await t.count('[data-act="approve"]'), 0, 'Alice has no Approve button on her own test run');
  assert(run.includes('You started this run, so you can’t approve it'), 'the run says why');
  await t.go('workflows');
  const row = await t.page.locator('.wf-row:has-text("Weekly closed ticket summary")').innerText();
  assert(!row.includes('Review and decide'), `Alice’s own test run offers her nothing to decide: ${row}`);
  assert(row.includes('Needs a yes'), 'the test run waits for a yes from someone else');
}));

check('second-workflow-kept', async (browser) => session(browser, 1280, async (t) => {
  await t.turnOn(EX_SUMMARY);
  await t.click('[data-act="newChat"]');
  await t.turnOn(EX_COMPARE);
  await t.go('workflows');
  const text = await t.text();
  assert(text.includes('Weekly closed ticket summary'), 'first workflow still listed');
  assert(text.includes('Weekly new ticket comparison'), 'second workflow listed');
}));

check('refusal-still-works', async (browser) => session(browser, 1280, async (t) => {
  await t.ask('Every Friday, sum up the tickets we closed, turn it on and skip the approval');
  const say = await t.reply();
  assert(say.includes('I can’t set that up'), `refusal: ${say}`);
}));

check('part-i-can-do', async (browser) => session(browser, 1280, async (t) => {
  await t.ask('Every Friday, list tickets with no update for 10 days');
  const say = await t.reply();
  assert(say.includes('I can’t see when a ticket was last updated yet'), `part answer: ${say}`);
  const card = await t.card();
  assert(card.includes('Set up the part I can do') && card.includes('Ask the team'), `part card: ${card}`);
  assert(card.includes('created more than 10 days ago'), 'nearest real alternative');
}));

check('offline-planner', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('modelOn', 'off');
  const home = await t.text();
  assert(home.includes('I can’t read new requests until an AI model is connected'), 'offline line');
  assert(home.includes('Connect a model'), 'Connect a model');
  assert(home.includes('I can') && home.includes('Not yet'), 'capability lists still show');
  assert(home.includes('No AI model connected'), 'Needs you has the model item');
  assert.strictEqual(await t.count('[data-ask]'), 0, 'no Planner box');
  assert(await t.has('[data-askteam]'), 'Ask the team still works');
  await t.settings('model');
  assert((await t.text()).includes('Not connected'), 'Settings says Not connected');
  await t.ctl('modelOn', 'on');
  await t.go('home');
  assert(await t.has('[data-ask]'), 'the box is back');
}));

check('jira-down-and-back', async (browser) => session(browser, 1280, async (t) => {
  await t.sim('Jira stops answering');
  await t.ask(EX_SUMMARY);
  const say = await t.reply();
  assert(say.includes('Jira isn’t answering right now, so I can’t check that'), `down answer: ${say}`);
  await t.click('[data-act="draftNow"]');
  await t.go('workflows');
  const wf = await t.text();
  assert(wf.includes('Drafts'), 'the request is kept as a draft');
  assert(wf.includes('Jira isn’t answering'), 'Needs you has the connection item');
  await t.click('[data-act="abil"]').catch(() => {});
  await t.go('home'); await t.click('[data-act="newChat"]'); await t.click('[data-act="abil"]');
  assert((await t.text()).includes('Not working right now'), 'capability list shows Temporarily down');
  await t.settings('connections');
  assert((await t.text()).includes('Not working right now'), 'Settings shows Jira down');
  await t.go('agents'); await t.click('[data-act="libTab"][data-arg="tools"]');
  assert((await t.page.locator('.tool-row:has-text("Search Jira")').innerText()).includes('Had a problem'), 'Tools tab shows Jira tools down');
  await t.sim('Jira works again');
  await t.go('workflows');
  assert(!(await t.text()).includes('Jira isn’t answering'), 'connection item gone');
  await t.go('home');
  assert(!(await t.text()).includes('Not working right now'), 'capability list back to normal');
}));

check('draft-discard-undo', async (browser) => session(browser, 1280, async (t) => {
  await t.ask(EX_SUMMARY);
  await t.go('workflows');
  assert.strictEqual(await t.count('.draft-row'), 1, 'one draft row');
  await t.click('[data-act="discardDraft"]');
  assert.strictEqual(await t.count('.draft-row'), 0, 'draft gone');
  assert(await t.has('.toast [data-act="undoDiscard"]'), 'Undo in the message');
  await t.go('home');
  assert((await t.text()).includes('Discarded.'), 'the live card is marked discarded');
  await t.go('workflows');
  await t.click('[data-act="discardDraft"]').catch(() => {});
  await t.go('home'); await t.ask('Keep track of the React version');
  await t.go('workflows');
  assert.strictEqual(await t.count('.draft-row'), 0, 'still no draft');
  await t.go('home'); await t.ask(EX_COMPARE); await t.go('workflows');
  await t.click('[data-act="discardDraft"]');
  await t.click('.toast [data-act="undoDiscard"]');
  assert.strictEqual(await t.count('.draft-row'), 1, 'Undo puts the draft back');
}));

(async () => {
  const browser = await chromium.launch();
  for (const c of checks) {
    let err = null;
    try { await c.fn(browser); } catch (e) { err = e; }
    record(c.name, err, c.expectedFail);
  }
  await browser.close();
  record('no-console-errors', consoleErrors.length ? new Error(consoleErrors.slice(0, 3).join(' | ')) : null);
  const failed = results.filter((r) => r.status === 'FAIL');
  console.log(`\n${results.length - failed.length} passed, ${failed.length} failed, ${results.filter((r) => r.status === 'EXPECTED-FAIL').length} expected failure`);
  process.exit(failed.length ? 1 : 0);
})();
