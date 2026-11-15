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
  const errors = [];
  page.on('pageerror', (e) => { errors.push(e.message); consoleErrors.push(`pageerror @${width}: ${e.message}`); });
  page.on('console', (m) => { if (m.type() === 'error') { errors.push(m.text()); consoleErrors.push(`console @${width}: ${m.text()}`); } });
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
    /* Fix round C: a Planner request that throws fails the check that sent it, not only the run's last line. */
    ask: async (text) => {
      const before = errors.length;
      await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await page.waitForTimeout(700);
      assert.deepStrictEqual(errors.slice(before), [], `the Planner request “${text}” raised a page or console error`);
    },
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
const TEAMS_ALLOWED = /\b(yes|approv|asked|ask |request|decide|decision|nothing (else )?(is|was) posted|practice copy|open in|reaches the real|teams answered|signed in|carries approval|isn’t built|planned)/i;
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
  await t.click('[data-act="libTab"][data-arg="agents"]'); await grab('agent cards');
  await t.click('[data-act="libTab"][data-arg="tools"]'); await grab('tools');
  await t.click('[data-act="toolOpen"][data-arg="jiraCreate"]'); seen.push(['tool dialog', await t.page.innerText('.dialog')]); await t.page.keyboard.press('Escape'); await t.wait(150);
  for (const tab of ['model', 'connections', 'people']) { await t.settings(tab); await grab(`settings ${tab}`); }
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
  /* The What it can do tab lists the registry's Not yet lines by name, so it is read without that group. */
  await t.go('agents'); texts.push(await t.page.evaluate(() => { const m = document.querySelector('main').cloneNode(true); m.querySelectorAll('.cap-not').forEach((e) => e.remove()); return m.textContent; }));
  await t.click('[data-act="libTab"][data-arg="agents"]'); texts.push(await t.text());
  await t.click('[data-act="libTab"][data-arg="tools"]'); texts.push(await t.text());
  /* LangServe is a real GitHub project on the watchlist. Its moved-address item is in Needs you (fix round A, item 12). */
  const bad = texts.flatMap((x) => x.match(/GitHub issues|bug reports? on|Entra|GitLab|admin tools|Issue reader|Access checker|Message writer|Post in Teams/gi) || []);
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
  /* The agent dialog is read only by default (changing an agent in plain English is Planned), so it asks nothing. */
  await t.click('[data-act="libTab"][data-arg="agents"]');
  await t.click('[data-act="agent"][data-arg="writer"]');
  assert.strictEqual(await t.count('#agent-text'), 0, 'the agent dialog has no change box by default');
  assert((await t.page.innerText('.dialog')).includes('Agents are read only here'), 'the dialog says it is read only');
}));

check('i4-todays-rule-everywhere', async (browser) => session(browser, 1280, async (t) => {
  await t.ask(EX_SUMMARY);
  assert((await t.card()).includes('Any Approver on your team except you'), 'set-up card uses today’s rule');
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="issues"]');
  const wf = await t.text();
  assert(/any Approver except (Alice|you)/i.test(wf), `workflow page: ${wf.match(/Approval[^\n]*\n[^\n]*/)}`);
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
  await t.go('agents'); await t.click('[data-act="libTab"][data-arg="agents"]');
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
  assert(/GitHub releases\s+Ready/.test(text), 'source states from the registry');
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
  await t.go('agents'); await t.click('[data-act="libTab"][data-arg="agents"]'); assert((await t.page.locator('.agent-lg:has-text("Vulnerability checker") .tag.planned').count()) === 1, 'planned agent tagged');
  await t.click('[data-act="libTab"][data-arg="tools"]'); assert((await t.page.locator('.tool-row:has-text("Post in Teams") .tag.planned').count()) === 1, 'planned tool tagged');
  await t.go('software'); assert((await t.page.locator('section:has-text("Security risks") .tag.planned').count()) >= 1, 'security findings tagged');
}));

check('two-approvers-access-review', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('preview', 'on');
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="access"]');
  await t.click('details.tech summary');
  const text = await t.text();
  assert(/First Bob.*Then Alice/.test(text), `two Approvers in turn: ${text.match(/Who approves[^\n]*\n[^\n]*/)}`);
  assert(text.includes('2 Approvers, one after the other'), 'plan says two Approvers');
}));

check('teams-drawer-no-approve', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('user', 'bob');
  const drawer = await t.teams();
  /* Whatever a button is called, the only ones in the cards open the Builder; nothing in Teams decides. */
  const buttons = await t.page.$$eval('.drawer .msg-card button', (els) => els.map((e) => `${e.dataset.act}:${e.textContent.trim()}`));
  assert(buttons.length >= 1, 'the cards have a button');
  assert.deepStrictEqual(buttons.filter((b) => !/^(run|toolOpen):Open in AI Workflow Builder$/.test(b)), [], `only Open buttons in the cards: ${buttons.join(' | ')}`);
  assert.strictEqual(await t.count('.drawer [data-act="approve"], .drawer [data-act="decline"], .drawer [data-act="yesAs"]'), 0, 'no decision action in Teams');
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
  assert(run.includes('started this run, so another Approver must decide'), 'the run says why');
  await t.go('workflows');
  const row = await t.page.locator('.wf-row:has-text("Friday closed ticket summary")').innerText();
  assert(!row.includes('Review and decide'), `Alice’s own test run offers her nothing to decide: ${row}`);
  assert(row.includes('Waiting for a yes'), 'the test run waits for a yes from someone else');
}));

check('second-workflow-kept', async (browser) => session(browser, 1280, async (t) => {
  await t.turnOn(EX_SUMMARY);
  await t.click('[data-act="newChat"]');
  await t.turnOn(EX_COMPARE);
  await t.go('workflows');
  const text = await t.text();
  assert(text.includes('Friday closed ticket summary'), 'first workflow still listed');
  assert(text.includes('Monday new ticket comparison'), 'second workflow listed');
  assert(text.includes('Weekly closed-ticket summary'), 'the sample workflow is still listed');
  const names = await t.page.$$eval('.wf-row h2', (els) => els.map((e) => e.textContent.trim()));
  assert.strictEqual(new Set(names).size, names.length, `every workflow has its own name: ${names.join(' | ')}`);
  assert(!names.some((n) => n === 'Weekly closed ticket summary'), 'the day-one example no longer takes the sample’s near-twin name');
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
  assert(card.includes('List the open tickets instead'), 'the nearest real alternative: a search can’t filter by age (SEARCH_LIMIT 50)');
  await t.click('.thread [data-act="instead"]'); await t.wait(600);
  assert.strictEqual(await t.count('.thread .pcard-f [data-act="turnOn"]'), 1, 'Set up the part I can do makes a set-up card, not another part answer');
}));

check('offline-planner', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('modelOn', 'off');
  const home = await t.text();
  assert(home.includes('I can’t read new requests until an AI model is connected'), 'offline line');
  assert(home.includes('Connect a model'), 'Connect a model');
  assert(home.includes('I can') && home.includes('Not yet'), 'capability lists still show');
  /* The hero is the model item, so the strip leaves its row out and Connect a model appears once. Workflows and the tab still count it. */
  assert.strictEqual(await t.page.locator('main button:has-text("Connect a model")').count(), 1, 'Connect a model appears once on Home');
  assert(!home.includes('No AI model connected'), 'the strip has no second model row');
  await t.go('workflows');
  assert((await t.text()).includes('No AI model connected'), 'Workflows lists the model item');
  await t.go('home');
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
  /* Validation: while Jira is down no screen may say it is working again, and a retry must not succeed. */
  assert(!/working again|answering again/.test(wf), `Workflows does not contradict the connection: ${wf.match(/[^\n]*again[^\n]*/)}`);
  await t.click('[data-act="workflow"][data-arg="issues"]');
  assert(!/working again|answering again/.test(await t.text()), 'the workflow page does not contradict the connection');
  await t.click('[data-act="retryIssues"]'); await t.wait(300);
  assert(!(await t.text()).includes('Done'), 'the retry does not succeed while Jira is down');
  await t.go('workflows');
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


/* Fix round A, item 1: the parties of a run (owner, starter, retrier) can never approve it, read from live state. */
check('owner-after-schedule-save-cannot-approve', async (browser) => session(browser, 1280, async (t) => {
  assert.strictEqual(await t.count('[data-act="run"][data-arg="sw"]'), 1, 'before: Alice, who is not a party, has Review and decide');
  await t.go('software');
  await t.click('[data-act="editSched"][data-arg="sw"]'); await t.click('[data-act="saveSched"][data-arg="sw"]');
  const how = await t.text();
  assert(how.includes('Set by Alice. Its checks count as the work of Alice and Carol, who can’t approve them.'), `the watchlist names both parties: ${how.match(/Set by[^\n]*/)}`);
  assert.strictEqual(await t.count('[data-act="run"][data-arg="sw"]'), 0, 'after: no Review and decide for the new owner');
  assert(how.includes('Waiting for Bob, Siti or Arun'), 'the watchlist says who it waits for');
  const drawer = await t.teams();
  assert(drawer.includes('Who can’t\nAlice, who set this up; Carol, who started this run. Nobody approves their own work.'), `the Teams card names who can’t and why: ${drawer.match(/Who can’t[^\n]*\n[^\n]*/)}`);
  assert(drawer.includes('Who can decide\nBob, Siti or Arun'), `and who can: ${drawer.match(/Who can decide[^\n]*\n[^\n]*/)}`);
  await t.click('.drawer [data-act="run"][data-arg="sw"]');
  assert.strictEqual(await t.count('[data-act="approve"]'), 0, 'no Approve on the run page for the owner');
  assert((await t.page.innerText('#decision')).includes('You set this up, so another Approver must decide. Nobody approves their own work.'), 'her part says why');
  await t.go('home');
  assert(!(await t.text()).includes('3 upgrade tickets are waiting for your yes'), 'Needs you no longer asks her to decide');
}));
check('control-owner-keeps-approve', async (browser) => session(browser, 1280, async (t) => {
  await t.go('software');
  await t.click('[data-act="editSched"][data-arg="sw"]'); await t.click('[data-act="saveSched"][data-arg="sw"]');
  assert.strictEqual(await t.count('[data-act="run"][data-arg="sw"]'), 1, 'seeded control: the new owner is still offered Review and decide');
}), { expectedFail: true });

/* Item 17: the Teams card reads the parties, so a retried run names the retrier. */
check('teams-card-names-parties', async (browser) => session(browser, 1280, async (t) => {
  let drawer = await t.teams();
  assert(drawer.includes('Who can’t\nCarol, who set this up and started this run.'), `the software card: ${drawer.match(/Who can’t[^\n]*\n[^\n]*/)}`);
  await t.closeTeams();
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="nudge"]'); await t.click('.panel [data-act="watch"][data-arg="nudge"]'); await t.wait(300);
  await t.click('#decision [data-act="report"]'); await t.click('[data-act="sendReport"]'); await t.page.keyboard.press('Escape'); await t.wait(200);
  for (let i = 0; i < 4; i += 1) { await t.openTest(); if (!(await t.page.$('.testctl button:has-text("Support moves case")'))) { await t.closeTest(); break; } await t.closeTest(); await t.sim('Support moves case'); }
  await t.click('#decision [data-act="retryNudge"]'); await t.wait(600);
  drawer = await t.teams();
  assert(drawer.includes('Who can’t\nAlice, who set this up and retried this run.'), `the retried summary's card: ${drawer.match(/Who can’t[^\n]*\n[^\n]*/)}`);
  assert(drawer.includes('Weekly closed-ticket summary, set up by Alice'), 'the owner comes from the workflow, not a fixed string');
}));

/* Item 16: with Planned features, the access review waits for two Approvers in turn, Bob then Alice. */
check('two-approvers-in-order', async (browser) => session(browser, 1280, async (t) => {
  await t.ctl('preview', 'on');
  await t.go('workflows');
  assert((await t.page.locator('.wf-row:has-text("Quarterly access review")').innerText()).includes('Waiting for a yes'), 'the access review waits');
  assert.strictEqual(await t.count('[data-act="run"][data-arg="access"]'), 0, 'Alice, the second Approver, cannot act before Bob');
  await t.ctl('user', 'bob');
  await t.go('home');
  assert((await t.text()).includes('3 people would lose access. Your yes is the first of two'), 'Bob is asked first');
  await t.click('[data-act="run"][data-arg="access"]'); await t.wait(300);
  const panel = await t.page.innerText('#decision');
  assert(panel.includes('3 people will lose access') && panel.includes('Jun Wei'), 'the panel lists the removals');
  assert(panel.includes('Carol started the review by hand'), 'who asked names the person who started it');
  assert.strictEqual(await t.count('[data-act="approve"][data-arg="access"]'), 1, 'Bob can decide step 1');
  await t.ctl('user', 'alice');
  assert.strictEqual(await t.count('[data-act="approve"][data-arg="access"]'), 0, 'Alice has no Approve before Bob');
  assert((await t.page.innerText('#decision')).includes('Only Bob or Siti can decide this one.'), 'her part says who can');
  await t.ctl('user', 'bob');
  await t.click('[data-act="approve"][data-arg="access"]'); await t.wait(300);
  assert((await t.page.innerText('.toast')).includes('Alice is asked next, as the second Approver.'), 'the yes moves it to step 2');
  assert.strictEqual(await t.count('[data-act="approve"][data-arg="access"]'), 0, 'Bob cannot approve step 2');
  await t.ctl('user', 'alice');
  assert((await t.page.innerText('#decision')).includes('Bob said yes. Your yes is the second of two.'), 'Alice sees the second step');
  assert.strictEqual(await t.count('[data-act="approve"][data-arg="access"]'), 1, 'and can decide it');
  await t.click('[data-act="approve"][data-arg="access"]'); await t.wait(600);
  assert((await t.text()).includes('3 people lost access'), 'the run finishes');
  assert((await t.page.innerText('#decision')).includes('Bob, then Alice, approved'), 'both yeses are recorded in order');
  const drawer = await t.teams();
  assert(/Approved by Bob at \d+:\d\d today, then Alice at \d+:\d\d today/.test(drawer), `Teams shows both: ${drawer.match(/Approved[^\n]*/)}`);
}));

/* Fix round B, synthesis 2: every alternative the Planner offers is one it can set up. Each request below gets a can't
   or a part answer; its alternative must open a set-up card with nothing red, and a request with no real alternative
   must offer only Ask the team. */
const ALTERNATIVES = [
  ['email', 'Every Friday, email me the tickets we closed this week'],
  ['slack', 'Every Friday, post the tickets we closed this week in Slack'],
  ['teams', 'Every Friday, put the tickets we closed this week in the support channel'],
  ['confluence', 'Every Friday, put the tickets we closed this week on a Confluence page'],
  ['nudge', 'Every Monday, remind the owners of open tickets'],
  ['updated', 'Every Friday, list tickets with no update for 10 days'],
  ['owners', 'Every Friday, list open tickets with their owners'],
  ['older', 'Every Monday, list open tickets created more than 30 days ago'],
  ['component', 'Every Monday, put new tickets in the Platform component'],
  ['confluence page update', 'Every Friday, update the Confluence page with the closed tickets'],
  ['wiki page update', 'Every Monday, update the wiki page with the open tickets'],
];
check('alternatives-are-real', async (browser) => session(browser, 1280, async (t) => {
  for (const [what, text] of ALTERNATIVES) {
    await t.ask(text);
    const card = await t.card();
    assert(/Set that up|Set up the part I can do/.test(card), `${what}: an alternative is offered: ${card}`);
    await t.click('.thread [data-act="instead"]'); await t.wait(600);
    assert.strictEqual(await t.count('.thread .pcard-f [data-act="turnOn"]'), 1, `${what}: the alternative opens a set-up card`);
    assert.strictEqual(await t.count('.thread .cmsg:last-child .schip.cant'), 0, `${what}: nothing red on the card`);
    assert.strictEqual(await t.count('.thread .cmsg:last-child .snotes .cant'), 0, `${what}: no can’t note on the card`);
    await t.click('[data-act="newChat"]');
  }
  await t.ask('Every Friday, close tickets with no update for 30 days');
  const card = await t.card();
  assert(!/Set that up|Set up the part/.test(card) && card.includes('Ask the team'), `no alternative for changing tickets, only Ask the team: ${card}`);
  assert(!/no update for 30 days|with their owners/.test(card), 'the old impossible offers are gone');
}));

/* Synthesis 3: Jira down is told as it is. The reason says Jira still isn't answering, and Retry can't run until it is back. */
check('jira-down-honest', async (browser) => session(browser, 1280, async (t) => {
  await t.sim('Jira stops answering');
  await t.ask('Why did Morning new-ticket check stop?');
  const card = await t.card();
  assert(card.includes('still isn’t answering'), `reason reads the connection: ${card}`);
  assert(!/maintenance|working again/.test(card), 'no invented cause and no false recovery');
  await t.click('.thread [data-act="retryIssues"]');
  assert((await t.page.innerText('body')).includes('Jira still isn’t answering, so the run can’t start'), 'Retry says it can’t run yet');
  await t.go('workflows');
  const wf = await t.text();
  assert(wf.includes('Morning new-ticket check stopped'), 'the stop is still a stop');
  assert(!wf.includes('maintenance'), 'Needs you has no invented cause');
  await t.sim('Jira works again');
  await t.go('home'); await t.click('[data-act="newChat"]'); await t.ask('Why did Morning new-ticket check stop?');
  const back = await t.card();
  assert(back.includes('answering again') && !back.includes('maintenance'), `after recovery, the reason says only what the run knows: ${back}`);
  await t.click('.thread [data-act="retryIssues"]'); await t.wait(400);
  assert((await t.text()).includes('Done'), 'the retry runs once Jira is back');
}));

/* Synthesis 15: approving automatically or approving your own requests is refused, and words like "ideas" or "to approve"
   inside a real task no longer take it over. */
check('refusal-and-word-rules', async (browser) => session(browser, 1280, async (t) => {
  const REFUSE = 'I can’t set that up. Anything that changes data waits for a yes, every time.';
  for (const text of ['Approve my own requests automatically', 'Approve it automatically', 'Auto-approve my requests', 'Approve my own requests', 'Don’t ask for approval']) {
    await t.ask(text);
    assert.strictEqual(await t.reply(), REFUSE, `refused alone: ${text}`);
    const card = await t.card();
    assert(card.includes('Nobody approves their own work') && !card.includes('Set it up with a yes'), `nothing to set up with a yes: ${card}`);
    await t.click('[data-act="newChat"]');
  }
  /* The same words inside a task, and after a card is already on screen. */
  for (const text of ['Every Friday, sum up the tickets we closed this week and approve it automatically', 'Every Monday, list open tickets, auto-approve the ticket', 'Every Friday, sum up closed tickets and don’t ask for approval', 'Every Friday, sum up closed tickets and approve my own requests']) {
    await t.ask(text);
    assert.strictEqual(await t.reply(), REFUSE, `refused inside a task: ${text}`);
    assert((await t.card()).includes('Set it up with a yes'), 'the safe version is offered');
    await t.click('[data-act="newChat"]');
  }
  await t.ask(EX_SUMMARY); await t.ask('Approve it automatically');
  assert.strictEqual(await t.reply(), REFUSE, 'refused after a card');
  await t.click('[data-act="newChat"]');
  await t.ask('Every Friday, list the tickets I need to approve');
  assert.strictEqual(await t.count('.thread .pcard-f [data-act="turnOn"]'), 1, '"to approve" inside a task still makes a set-up card');
  await t.click('[data-act="newChat"]');
  await t.ask('Every Monday, list the new tickets about ideas');
  assert.strictEqual(await t.count('.thread .pcard-f [data-act="turnOn"]'), 1, '"ideas" inside a task still makes a set-up card');
  await t.click('[data-act="newChat"]');
  await t.ask('What needs me?');
  assert(/things? needs? you/.test(await t.reply()), 'the short question still works');
}));

/* Synthesis 19 and 20: unsupported email wording, and "on" for workflows between runs. */
check('email-wording-and-on-not-running', async (browser) => session(browser, 1280, async (t) => {
  await t.ask('Every Friday, email me the tickets we closed this week');
  assert((await t.reply()).includes('Email isn’t on the team’s plan. Ask the team if you need it.'), await t.reply());
  assert(!/are running|keep running/.test(source), 'no workflow is described as running between runs');
  assert(!/maintenance/.test(source), 'no invented cause in the source');
}));

/* Synthesis 14: the morning check reads the last day and says it reads the 50 newest tickets; the registry names the limit. */
check('newest-50-and-last-day', async (browser) => session(browser, 1280, async (t) => {
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="issues"]');
  const wf = await t.text();
  assert(wf.includes('in the last day'), `the morning check reads the last day: ${wf.match(/Finds[^\n]*/)}`);
  await t.click('details.tech summary');
  assert((await t.text()).includes('Reads up to 50 matching tickets in Jira, newest first'), 'How it works names the 50-ticket limit');
  assert((await t.text()).includes('a busier day is cut short'), 'How it works says a busier day is cut short');
  assert(!/since the last run/.test(source), 'nothing claims to read since the last run');
  await t.go('agents'); await t.click('.cap-fold summary');
  assert((await t.page.innerText('.cap-not')).includes('Find older tickets, beyond the newest 50'), 'the registry has the Planned line');
  assert(!/created more than \d+ days ago/.test(source), 'the old-ticket starting point and alternative are gone');
}));

/* Fix round C: one number for what needs her. In a normal week and after one approval, the Needs you count on
   Workflows, the items listed there, the Workflows tab badge, Home's Needs you count and the Planner's "what needs me"
   answer, with its rows, all agree. */
async function needCounts(t) {
  const num = (s) => { const m = String(s).match(/\d+/); return m ? +m[0] : null; };
  await t.go('workflows');
  const c = {};
  c.workflows = num(await t.page.innerText('main #needs-h .count'));
  c.workflowsItems = (await t.count('main section[aria-labelledby="needs-h"] article.task')) + (await t.count('main section[aria-labelledby="needs-h"] .queue > li'));
  c.badge = num(await t.page.innerText(`${t.width > 900 ? '.hdr' : '.tabbar'} .badge[data-val="needs-n"]`).catch(() => ''));
  await t.go('home');
  c.home = num(await t.page.innerText('main #needs-h .count'));
  await t.ask('What needs me?');
  c.planner = num(await t.reply());
  c.plannerRows = await t.count('.thread .cmsg:last-child li.nrow');
  await t.click('[data-act="newChat"]');
  return c;
}
const agreeOn = (label, c) => assert.strictEqual(new Set(Object.values(c)).size, 1, `${label}: the counts differ: ${JSON.stringify(c)}`);
check('counts-agree', async (browser) => session(browser, 1280, async (t) => {
  agreeOn('normal week', await needCounts(t));
  await t.go('workflows'); await t.click('main [data-act="run"][data-arg="sw"]'); await t.click('[data-act="approve"][data-arg="sw"]');
  await t.page.waitForFunction(() => document.querySelector('main').innerText.includes('approved, and the platform created the tickets'), null, { timeout: 10000 });
  agreeOn('after one approval', await needCounts(t));
}));

/* Synthesis 18: one state-word function, and no dead helpers. */
check('one-state-word-source', () => {
  assert(!/CAP_WORD|isReleaseCheck/.test(source), 'CAP_WORD and isReleaseCheck are gone');
  assert.strictEqual((source.match(/'Not working right now'/g) || []).length, 1, 'the state words are written once');
  assert.strictEqual((source.match(/'Needs setup'/g) || []).length, 1, 'Needs setup is written once');
});

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
