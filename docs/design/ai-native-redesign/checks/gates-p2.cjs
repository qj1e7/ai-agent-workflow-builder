/* Gate checks for the P2 slice of the AI-native redesign: the Software watchlist, the Agent library and Settings.
   Usage: node docs/design/ai-native-redesign/checks/gates-p2.cjs <prototype.html>   (ONLY=text runs the checks whose name has that text)
   Runs named checks for spec sections 11, 12, 13 and 15 rule 8, at 1280 px and at 390 px, and re-runs gates-p0.cjs.
   One control check is seeded to fail, to prove the gate can fail; it is reported as an expected failure. */
const path = require('path');
const fs = require('fs');
const assert = require('assert');
const { execFileSync, spawnSync } = require('child_process');

const file = path.resolve(process.argv[2] || path.join(__dirname, '..', 'prototype.html'));
const here = path.resolve(__dirname, '..', '..', '..', '..');
const common = (() => { try { return path.dirname(path.resolve(here, execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: here }).toString().trim())); } catch (e) { return here; } })();
const searchPaths = [path.join(here, 'portal'), path.join(common, 'portal')];
const { chromium } = require(require.resolve('playwright', { paths: searchPaths }));
const axeSource = fs.readFileSync([...searchPaths.map((p) => path.join(p, 'node_modules', 'axe-core', 'axe.min.js'))].find((p) => fs.existsSync(p)), 'utf8');
const url = `file://${file}`;
const source = fs.readFileSync(file, 'utf8');

const results = [];
const consoleErrors = [];
const record = (name, err, expectedFail) => {
  const ok = !err;
  const status = expectedFail ? (ok ? 'FAIL' : 'EXPECTED-FAIL') : ok ? 'PASS' : 'FAIL';
  results.push({ name, status });
  console.log(`${status.padEnd(13)} ${name}${err ? `: ${String(err.message || err).split('\n')[0]}` : ''}${expectedFail && ok ? ': the seeded control passed, so the gate cannot fail' : ''}`);
};

async function session(browser, width, body) {
  const phone = width < 600;
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', colorScheme: 'light', hasTouch: phone, isMobile: phone });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => consoleErrors.push(`pageerror @${width}: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`console @${width}: ${m.text()}`); });
  await page.goto(url);
  await page.waitForTimeout(250);
  const t = {
    page, width,
    wait: (ms) => page.waitForTimeout(ms),
    text: () => page.innerText('main'),
    count: (sel) => page.$$eval(sel, (els) => els.length).catch(() => 0),
    has: async (sel) => (await page.$(sel)) !== null,
    click: async (sel) => { await page.click(sel); await page.waitForTimeout(220); },
    go: async (tab) => { await page.click(`${width > 900 ? '.nav-a' : '.tab'}[data-arg="${tab}"]`); await page.waitForTimeout(260); },
    openTest: async () => { if (!(await page.$('.testctl-panel'))) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    closeTest: async () => { if (await page.$('.testctl-panel')) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    ctl: async (act, arg) => { await t.openTest(); await page.click(`.testctl [data-act="${act}"][data-arg="${arg}"]`); await page.waitForTimeout(260); await t.closeTest(); },
    sim: async (label) => { await t.openTest(); await page.$eval(`.testctl button:has-text("${label}")`, (b) => b.click()); await page.waitForTimeout(260); await t.closeTest(); },
    settings: async (tab) => { await page.click('.hdr [data-act="go"][data-arg="settings"]'); await page.waitForTimeout(220); if (tab) { await page.click(`[data-act="setTab"][data-arg="${tab}"]`); await page.waitForTimeout(220); } },
    lib: async (tab) => { await t.go('agents'); await page.click(`[data-act="libTab"][data-arg="${tab}"]`); await page.waitForTimeout(220); },
    ask: async (text) => { await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await page.waitForTimeout(700); },
    card: () => page.locator('.thread .pcard').last().innerText(),
    overflow: () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
    axe: async () => {
      await page.evaluate(axeSource);
      const r = await page.evaluate(() => axe.run(document.querySelector('main'), { runOnly: ['wcag2a', 'wcag2aa'] }));
      return r.violations.map((v) => `${v.id} (${v.nodes.length})`);
    },
    small: () => page.evaluate(() => [...document.querySelectorAll('main button, main .btn, main .linkbtn, main input:not([type=hidden]):not([type=radio]):not([type=checkbox]), main select, main summary')].filter((e) => e.offsetParent && !e.closest('.vh') && !e.disabled && !e.classList.contains('rcard-link')).map((e) => { const b = e.getBoundingClientRect(); return { n: (e.textContent || e.name || e.id || e.tagName).trim().slice(0, 30), h: Math.round(b.height), w: Math.round(b.width) }; }).filter((x) => x.h < 44)),
  };
  try { await body(t); } finally { await ctx.close(); }
}

const checks = [];
const check = (name, fn, opts = {}) => checks.push({ name, fn, ...opts });
const both = (name, fn) => { for (const w of [1280, 390]) check(`${name}@${w}`, (b) => session(b, w, (t) => fn(t, w))); };

/* ---------- Static ---------- */
check('no-long-dashes', () => {
  const bad = source.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => /[—–]/.test(l)).map(([i]) => i);
  assert.deepStrictEqual(bad, [], `long dashes on lines ${bad.join(', ')}`);
});
check('no-themed-names', () => {
  const hits = (source.match(/\b(Flint|Forge|Striker|Spark Map|Scout|Analyst|Messenger|Clerk|Fixer|Kindling|Firebreak|Ember)\b/g) || []);
  assert.deepStrictEqual(hits, [], hits.join(', '));
});
check('no-new-looping-motion', () => {
  const base = execFileSync('git', ['diff', 'f1b55a7', '--', file], { cwd: here, maxBuffer: 1 << 26 }).toString();
  const added = base.split('\n').filter((l) => l.startsWith('+') && !l.startsWith('+++') && /infinite|animation:/.test(l));
  assert.deepStrictEqual(added, [], `added motion: ${added.join(' | ')}`);
});

/* ---------- Spec 11: the Software watchlist ---------- */
both('wl-order-needs-watch-how', async (t) => {
  await t.go('software');
  const heads = await t.page.$$eval('main h2', (h) => h.map((x) => x.textContent.replace(/\s+/g, ' ').trim().replace(/ \d+$/, '')));
  const want = ['Needs attention', 'Software we watch', 'How it’s checked'];
  assert.deepStrictEqual(heads.filter((h) => want.includes(h)), want, heads.join(' | '));
});
both('wl-needs-attention-items', async (t) => {
  await t.go('software');
  const n = await t.page.innerText('#sw-attn-h >> xpath=..');
  assert(n.includes('This week’s check wants to raise 3 upgrade tickets'), 'the upgrade request waits for a yes');
  assert(await t.has('[data-act="run"][data-arg="sw"]'), 'Review and decide');
  assert(n.includes('GitHub can’t find langchain-ai/langserve. It moved to langchain-ai/langchain.'), `moved note: ${n}`);
  assert((await t.page.innerText('[data-act="useNewAddress"]')).includes('Use the new address'), 'one click fixes it');
});
both('wl-use-new-address-and-undo', async (t) => {
  await t.go('software');
  await t.click('[data-act="useNewAddress"]');
  assert.strictEqual(await t.count('[data-act="useNewAddress"]'), 0, 'item gone after the click');
  const row = await t.page.innerText('tr[data-flip="sw:ls"]');
  assert(row.includes('langchain-ai/langchain') && row.includes('Not checked yet'), `row after fix: ${row}`);
  assert(await t.has('.toast [data-act="undoAddress"]'), 'Undo offered');
  await t.click('.toast [data-act="undoAddress"]');
  assert.strictEqual(await t.count('[data-act="useNewAddress"]'), 1, 'Undo puts the problem back');
});
both('wl-rows-have-the-five-facts', async (t) => {
  await t.go('software');
  const lg = await t.page.innerText('tr[data-flip="sw:lg"]');
  for (const part of ['LangGraph', '1.2.14', '1.2.17', 'New version', 'GitHub']) assert(lg.includes(part), `LangGraph row lacks ${part}: ${lg}`);
  assert((await t.page.innerText('tr[data-flip="sw:ok:n8n"]')).includes('Up to date'), 'Up to date row');
  assert((await t.page.innerText('tr[data-flip="sw:gr"]')).includes('Can’t check'), 'Can’t check row');
  assert.strictEqual(await t.count('.sw-table tbody tr[data-flip^="sw:"]'), 14, 'one row for each of the 14 software');
});
both('wl-add-one-match-shows-where-guess-came-from', async (t) => {
  await t.go('software');
  await t.page.fill('#sw-name', 'Playwright'); await t.page.keyboard.press('Enter'); await t.wait(250);
  const g = await t.page.innerText('.guess');
  assert(g.includes('microsoft/playwright') && /Found by name/.test(g) && /Checked just now/.test(g), `guess: ${g}`);
  assert(await t.has('.guess [data-act="swChange"]'), 'Change is offered');
  assert.strictEqual(await t.count('#sw-kind'), 0, 'no registry picker by default');
  await t.click('.guess button[type=submit]');
  assert((await t.page.innerText('tr[data-flip="sw:add0"]')).includes('Playwright'), 'added to the list');
});
both('wl-add-several-matches-choose', async (t) => {
  await t.go('software');
  await t.page.fill('#sw-name', 'Kubernetes'); await t.page.keyboard.press('Enter'); await t.wait(250);
  assert.strictEqual(await t.count('input[name="sw-pick"]'), 2, 'two projects match');
  assert(await t.page.$eval('.guess button[type=submit]', (b) => b.disabled), 'Add waits for a choice');
  await t.page.check('input[name="sw-pick"][value="1"]'); await t.wait(250);
  assert(!(await t.page.$eval('.guess button[type=submit]', (b) => b.disabled)), 'Add is ready after a choice');
  await t.click('.guess button[type=submit]');
  assert((await t.page.innerText('tr[data-flip="sw:add0"]')).includes('kubernetes-client/python'), 'the chosen project is on the list');
});
both('wl-add-nothing-found-falls-back-to-a-link', async (t) => {
  await t.go('software');
  await t.page.fill('#sw-name', 'Zebra tool'); await t.page.keyboard.press('Enter'); await t.wait(250);
  assert((await t.page.innerText('.guess')).includes('I couldn’t find “Zebra tool”'), 'says nothing was found');
  await t.page.fill('#sw-repo', 'not a project'); await t.click('.guess button[type=submit]');
  assert(await t.has('#sw-repo-err'), 'a bad link gets an error');
  await t.page.fill('#sw-repo', 'https://github.com/zebra/tool'); await t.click('.guess button[type=submit]');
  assert((await t.page.innerText('tr[data-flip="sw:add0"]')).includes('zebra/tool'), 'a pasted link is accepted');
});
both('int-watchlist-run-count-matches-rows', async (t) => {
  await t.go('software');
  const rows = await t.count('tr[data-flip^="sw:"]');
  const unread = await t.page.$$eval('tr[data-flip^="sw:"]', (els) => els.filter((e) => e.innerText.includes('Can’t check')).length);
  assert.strictEqual(unread, 2, 'two rows can’t be read');
  await t.page.click('[data-act="run"][data-arg="sw"]'); await t.wait(400);
  const x = await t.page.innerText('body');
  assert(x.includes(`Read ${rows - unread} of ${rows}`), `the run reads ${rows - unread} of ${rows}`);
  assert(!/Read 14 (projects|sources)/.test(x), 'the old count is gone');
});
both('wl-how-its-checked', async (t) => {
  await t.go('software');
  const h = await t.page.innerText('#sw-how-h >> xpath=..');
  for (const part of ['Every Monday at 9:00', 'Singapore time', 'One approval covers all the upgrade tickets', 'Who approves: Any Approver except Carol']) assert(h.includes(part), `lacks ${part}: ${h}`);
  assert(/GitHub releases\s+Ready/.test(h), 'GitHub releases are Ready');
  /* Fix round B, synthesis 4: a planned source is a plain Not yet by default; the Planned tag comes with Planned features. */
  for (const s of ['Package registries', 'Security advisories', 'Support end dates']) assert(new RegExp(`${s}\\s+Not yet`).test(h), `${s} is Not yet`);
  const all = await t.text();
  assert(!/vulnerab|severity|Critical security risk|Security risks|Support ending/i.test(all), 'no findings or severity by default');
  assert.strictEqual(await t.count('.tag.planned'), 0, 'no Planned tag by default');
});
both('wl-planned-findings-only-with-preview', async (t) => {
  await t.ctl('preview', 'on'); await t.go('software');
  const sec = await t.page.innerText('#sw-attn-h >> xpath=..');
  assert(/Security risks/.test(sec) && /Critical/.test(sec), 'severity shows');
  assert((await t.page.locator('#sw-attn-h >> xpath=.. >> .tag.planned').count()) >= 1, 'findings are tagged Planned');
  assert((await t.page.locator('#sw-how-h >> xpath=.. >> .srcs .tag.planned').count()) === 3, 'three Planned sources tagged');
});
both('wl-day-one', async (t) => {
  await t.ctl('day', 'one'); await t.go('software');
  const x = await t.text();
  assert(!x.includes('Needs attention'), 'no Needs attention on day one');
  assert(x.includes('No software yet') && x.includes('How it’s checked'), 'empty state and the schedule');
  assert.strictEqual(await t.count('.sw-table'), 0, 'no table');
});
both('wl-approver-only', async (t) => {
  await t.ctl('user', 'bob'); await t.go('software');
  const x = await t.text();
  assert(x.includes('An Operator can fix this.'), 'Bob is told who can fix it');
  assert.strictEqual(await t.count('[data-act="useNewAddress"], #sw-name'), 0, 'no fix button and no Add for an Approver');
  assert(await t.has('[data-act="run"][data-arg="sw"]'), 'Bob can review and decide');
});
both('wl-keyboard-focus-ring', async (t) => {
  await t.go('software');
  let ok = false;
  for (let i = 0; i < 80 && !ok; i++) {
    await t.page.keyboard.press('Tab');
    ok = await t.page.evaluate(() => document.activeElement && document.activeElement.matches('[data-act="useNewAddress"]'));
  }
  assert(ok, 'Use the new address is reachable by Tab');
  const ring = await t.page.evaluate(() => { const cs = getComputedStyle(document.activeElement); return { fv: document.activeElement.matches(':focus-visible'), outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0, shadow: cs.boxShadow !== 'none' }; });
  assert(ring.fv && (ring.outline || ring.shadow), `focus ring: ${JSON.stringify(ring)}`);
  await t.page.keyboard.press('Enter'); await t.wait(250);
  assert.strictEqual(await t.count('[data-act="useNewAddress"]'), 0, 'Enter fixes it');
});

/* ---------- Spec 12: the Agent library ---------- */
both('lib-opens-on-what-it-can-do', async (t) => {
  await t.go('agents');
  assert.strictEqual(await t.page.getAttribute('[data-act="libTab"][data-arg="can"]', 'aria-pressed'), 'true', 'opening tab');
  const labels = await t.page.$$eval('.lib-tabs button', (b) => b.map((x) => x.textContent.replace(/\s+\d+$/, '').trim()));
  assert.deepStrictEqual(labels, ['What it can do', 'Agents', 'Tools']);
  const heads = await t.page.$$eval('main h2', (h) => h.map((x) => x.textContent.replace(/\s+/g, ' ').trim().replace(/ \d+$/, '')));
  assert.deepStrictEqual(heads, ['I can', 'Not yet'], heads.join(' | '));
  const can = await t.page.innerText('.cap-ready');
  assert(/Read Jira tickets\s+Used by Jira reader/.test(can), `agents named: ${can}`);
  assert(/Check software for new releases on GitHub\s+Used by Version checker/.test(can), 'GitHub line names its agent');
  assert(/Create a Jira ticket after a yes\s+Used by Ticket writer/.test(can), 'create line names its agent');
  assert(/Ask Approvers for a yes in Teams\s+The platform does this/.test(can), 'platform line');
  assert((await t.page.innerText('.cap-not')).includes('Post messages in Teams'), 'Not yet lists the planned lines');
});
both('lib-down-and-setup-groups', async (t) => {
  await t.sim('Jira stops answering'); await t.go('agents');
  const down = await t.page.innerText('.cap-down');
  assert(/Read Jira tickets[\s\S]*Used by Jira reader/.test(down) && /Last seen working/.test(down), `down group: ${down}`);
  await t.sim('Jira works again');
});
both('lib-agents-cards-and-details', async (t) => {
  await t.lib('agents');
  const card = await t.page.innerText('.agent-lg:has-text("Jira reader")');
  assert(card.includes('Finds and reads Jira tickets.') && /Reads only/.test(card), card);
  assert(!/\d tools?\b/.test(card), 'no tool counts on the card');
  await t.click('.agent-lg:has-text("Ticket writer") [data-act="agent"].btn');
  assert.strictEqual(await t.page.$eval('.agent-details', (d) => d.open), false, 'steps and tools sit inside a closed Details');
  const dlg = await t.page.innerText('.dialog');
  assert(!/Tools it may use/.test(dlg) || !(await t.page.locator('.agent-details >> text=Tools it may use').isVisible()), 'tools hidden until Details opens');
  await t.page.click('.agent-details > summary'); await t.wait(150);
  const open = await t.page.innerText('.agent-details');
  for (const part of ['How it works', 'Tools it may use', 'Permissions and rules']) assert(open.includes(part), `Details lacks ${part}`);
});
both('lib-change-shows-the-exact-difference', async (t) => {
  /* Fix round B, synthesis 4: changing an agent in plain English is Planned, so the dialog is read only by default. */
  await t.lib('agents'); await t.click('.agent-lg:has-text("Ticket writer") [data-act="agent"].btn');
  assert.strictEqual(await t.count('#agent-text'), 0, 'read only by default');
  await t.page.keyboard.press('Escape'); await t.wait(150);
  await t.ctl('preview', 'on');
  await t.lib('agents'); await t.click('.agent-lg:has-text("Ticket writer") [data-act="agent"].btn');
  assert((await t.page.locator('.agent-change .tag.planned').count()) === 1, 'tagged Planned when shown');
  const chips = await t.page.$$eval('.agent-change .chip', (els) => els.map((e) => e.textContent.trim()));
  assert(!chips.some((c) => /component/i.test(c)), `suggestions use only Ready capabilities: ${chips.join(' | ')}`);
  await t.page.fill('#agent-text', 'Add the release notes link to every ticket'); await t.click('[data-act="agentSuggest"]');
  const p = await t.page.innerText('#agent-proposal');
  assert(p.includes('exact difference'), 'says it shows the exact difference');
  assert(await t.has('#agent-proposal del') && await t.has('#agent-proposal ins'), 'old step crossed out, new step marked');
  assert(await t.has('[data-act="agentSave"]') && await t.has('[data-act="agentDiscard"]'), 'save and discard come after the difference');
});
both('lib-tools-plain-and-healthy', async (t) => {
  await t.lib('tools');
  const row = await t.page.innerText('.tool-row:has-text("Create a Jira ticket")');
  assert(/Needs a yes/.test(row) && /Working|Had a problem/.test(row), row);
  assert(!/Used by/.test(row), 'no agent column');
  await t.sim('Jira stops answering'); await t.lib('tools');
  assert((await t.page.innerText('.tool-row:has-text("Search Jira")')).includes('Had a problem'), 'health comes from the registry');
});

/* ---------- Spec 13: Settings ---------- */
both('set-groups-and-connections', async (t) => {
  await t.settings();
  const labels = await t.page.$$eval('.set-tabs button', (b) => b.map((x) => x.textContent.replace(/\(needs attention\)/, '').trim()));
  /* Fix round B, synthesis 4: Usage is a design only, and replacing a key is ADR 0039, so both show only with Planned features. */
  assert.deepStrictEqual(labels, ['Connections', 'People and permissions', 'AI model']);
  assert.strictEqual(await t.page.getAttribute('.set-tabs [data-arg="connections"]', 'aria-pressed'), 'true', 'Connections opens first');
  const x = await t.text();
  assert(x.includes('Jira is working. Checked today, 9:00.'), 'plain sentence');
  assert(/Sends approval requests to Approvers/.test(await t.page.innerText('.conn:has-text("Microsoft Teams")')), 'Teams description');
  assert(/What uses it\s+Read Jira tickets; Create a Jira ticket after a yes/.test(await t.page.innerText('.conn:has-text("Jira")')), 'what uses it comes from the registry');
  assert(x.includes('The GitHub key runs out in 9 days. Ask whoever looks after the platform to replace it before Thu 5 Nov, or the Software watchlist stops.'), 'running-out sentence says who to ask');
  assert(!(await t.has('[data-act="connReplace"]')), 'no Replace the key by default');
  assert(await t.has('[data-act="connTest"][data-arg="github"]'), 'Check now stays');
  assert.strictEqual(await t.page.evaluate(() => { const s = document.querySelector('.set-tabs'); return s.scrollWidth - s.clientWidth; }), 0, 'the Settings tabs do not overflow');
  await t.ctl('preview', 'on'); await t.settings('connections');
  assert(await t.has('[data-act="connReplace"][data-arg="github"] .tag.planned'), 'Replace the key shows tagged Planned');
  assert((await t.text()).includes('Replace it before Thu 5 Nov'), 'the sentence then offers the fix');
  const keys = await t.page.$$eval('.conn dl dd', (d) => d.map((x) => x.textContent).filter((s) => /^Ends in/.test(s)));
  assert(keys.length === 3 && keys.every((k) => /^Ends in [A-Za-z0-9]{2}\b/.test(k)), `keys show two characters: ${keys}`);
});
both('set-down-and-refused-states', async (t) => {
  await t.sim('Jira stops answering'); await t.settings('connections');
  let jira = await t.page.innerText('.conn:has-text("Jira")');
  assert(/Jira isn’t answering\. Last seen working today, 9:00/.test(jira), jira);
  assert(await t.page.$eval('[data-act="connTest"][data-arg="jira"]', (b) => b.classList.contains('primary')), 'Check now is the recovery button');
  assert(await t.page.$eval('.set-tabs [data-arg="connections"]', (b) => !!b.querySelector('.tab-dot')), 'the tab shows it needs attention');
  await t.click('[data-act="connTest"][data-arg="jira"]'); await t.wait(900);
  assert(/still isn’t answering/.test(await t.page.innerText('.conn:has-text("Jira")')), 'honest result');
  await t.sim('Jira works again');
  assert(!/isn’t answering/.test(await t.text()), 'back to working');
});
both('set-usage-and-replace-key-marked-unbuilt', async (t) => {
  await t.settings();
  assert(!(await t.has('[data-act="setTab"][data-arg="usage"]')), 'no Usage tab by default');
  await t.ctl('preview', 'on');
  await t.settings('usage');
  assert(await t.has('main [data-unbuilt*="usage"]'), 'Usage is marked data-unbuilt');
  assert(await t.has('main h2 .tag.planned'), 'and tagged Planned');
  await t.settings('connections');
  assert(await t.has('[data-act="connReplace"][data-unbuilt]'), 'Replace the key marked');
  await t.go('software');
  assert(await t.has('[data-act="useNewAddress"][data-unbuilt]'), 'Use the new address marked');
  await t.ctl('markUnbuilt', 'on');
  assert((await t.page.locator('.mark-unbuilt [data-unbuilt]').count()) >= 1, 'outlines show');
});
/* Synthesis 4 and 5: what is hidden until Planned features are shown, and the marks that follow the plan's "Prototype only" cells. */
both('planned-hidden-by-default', async (t) => {
  await t.go('workflows'); await t.click('[data-act="report"]'); await t.click('[data-act="sendReport"]'); await t.page.keyboard.press('Escape'); await t.wait(200);
  const track = await t.page.innerText('.track4');
  assert(!/Agents are writing a fix|Coding agents|support developer/.test(track), `no coding-agent stages by default: ${track}`);
  assert(/Reported[\s\S]*Support is looking at it[\s\S]*Fixed/.test(track), 'the default track');
  await t.go('home'); await t.ask('Every month at 9:00, sum up the tickets we closed');
  assert((await t.card()).includes('I can’t run things monthly yet'), 'monthly is not understood by default');
  await t.click('[data-act="whenOpen"]');
  assert(!(await t.page.$$eval('#sched-freq option', (o) => o.map((x) => x.textContent))).includes('Every month'), 'no Every month in the picker');
  await t.ctl('preview', 'on');
  await t.go('workflows'); await t.click('[data-act="workflow"][data-arg="nudge"]');
  const shown = await t.page.innerText('.track4');
  assert(/Agents are writing a fix/.test(shown) && (await t.page.locator('.track4 .tag.planned').count()) >= 1, 'coding-agent stages show tagged with Planned features');
  await t.go('home'); await t.click('[data-act="newChat"]'); await t.ask('Every month at 9:00, sum up the tickets we closed');
  assert((await t.card()).includes('Every month on the 1st at 9:00'), 'monthly is understood with Planned features');
});
both('marks-follow-the-plan', async (t) => {
  assert.strictEqual(await t.count('.home .needs[data-unbuilt]'), 0, 'Needs you on Home is built, so it carries no mark');
  assert(await t.has('.home [data-act="abil"][data-unbuilt]'), 'What can I ask for is marked');
  await t.ask('Every Friday, email me the tickets we closed this week');
  assert(await t.has('.thread [data-act="teamReq"][data-unbuilt]'), 'Ask the team is marked');
  await t.click('[data-act="instead"]'); await t.wait(600);
  assert(await t.has('.thread .pcard[data-unbuilt*="set-up card"]'), 'the set-up card is marked');
  await t.go('workflows');
  assert(await t.has('[data-act="discardDraft"][data-unbuilt]'), 'Discard is marked');
  await t.go('agents');
  assert(await t.has('main [data-unbuilt*="What it can do"]'), 'What it can do is marked');
  await t.settings('connections');
  assert(await t.has('main [data-unbuilt*="Connection health"]'), 'connection health is marked');
  await t.ctl('modelOn', 'off'); await t.go('home');
  assert(await t.has('.home[data-unbuilt*="offline"]') && await t.has('.team-ask[data-unbuilt]'), 'the offline Home and its Ask the team box are marked');
});
/* Validation: the watchlist, the history and the approval panel name the same newest version; tool health is the registry's. */
both('one-newest-version-and-registry-health', async (t) => {
  await t.go('software');
  const row = await t.page.innerText('tr[data-flip="sw:fa"]');
  assert(row.includes('0.120.1') && !row.includes('0.120.2'), `the FastAPI row agrees with the request: ${row.replace(/\s+/g, ' ')}`);
  await t.click('[data-act="swHist"][data-arg="fa"]'); await t.wait(200);
  assert((await t.text()).includes('Found 0.120.1'), 'the history agrees');
  await t.ctl('user', 'bob'); await t.click('[data-act="run"][data-arg="sw"]'); await t.wait(400);
  const run = await t.text();
  assert(run.includes('0.120.1') && !run.includes('0.120.2'), 'the approval panel agrees');
  await t.ctl('user', 'alice'); await t.lib('tools');
  const rows = await t.page.$$eval('.tool-row', (els) => els.map((e) => e.innerText.replace(/\s+/g, ' ')));
  assert(rows.every((r) => /Working/.test(r) && !/Had a problem/.test(r)), `tools are healthy while Jira works: ${rows.join(' | ')}`);
});
/* Validation: the phone placeholder fits its box. */
check('phone-placeholder-fits@390', (b) => session(b, 390, async (t) => {
  const fits = await t.page.evaluate(() => {
    const ta = document.querySelector('[data-ask]');
    const c = document.createElement('canvas').getContext('2d');
    const cs = getComputedStyle(ta);
    c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    return c.measureText(ta.placeholder).width <= ta.clientWidth;
  });
  assert(fits, 'the placeholder is not cut off at 390 px');
}));
both('set-people-and-model', async (t) => {
  await t.settings('people');
  assert((await t.text()).includes('People and permissions'), 'renamed');
  await t.page.fill('#np-name', 'Mei Ling'); await t.page.click('[data-submit="personAdd"] button[type=submit]'); await t.wait(200);
  assert(await t.has('#np-email-err'), 'work email is asked for');
  await t.page.fill('#np-email', 'mei.ling@example.com'); await t.page.click('[data-submit="personAdd"] button[type=submit]'); await t.wait(250);
  assert((await t.text()).includes('Mei Ling'), 'person added');
  await t.ctl('modelOn', 'off'); await t.settings('model');
  assert((await t.text()).includes('Whoever looks after the platform connects it here'), 'handoff line');
  await t.ctl('modelOn', 'on');
});

/* ---------- Spec 15 rule 8: accessible, on every screen touched ---------- */
both('a11y-no-sideways-scroll-axe-and-targets', async (t, w) => {
  const screens = [['watchlist', async () => { await t.go('software'); }], ['what it can do', async () => { await t.go('agents'); }], ['agents', async () => { await t.lib('agents'); }], ['tools', async () => { await t.lib('tools'); }],
    ['connections', async () => { await t.settings('connections'); }], ['people', async () => { await t.settings('people'); }], ['model', async () => { await t.settings('model'); }], ['usage', async () => { await t.ctl('preview', 'on'); await t.settings('usage'); }]];
  /* The Usage screen needs Planned features; the add flow below is checked without them, as the product ships. */
  const addFlow = async () => { await t.ctl('preview', 'off'); await t.go('software'); };
  const bad = [];
  for (const [name, open] of screens) {
    await open();
    const o = await t.overflow(); if (o > 0) bad.push(`${name} scrolls sideways by ${o}px`);
    const v = await t.axe(); if (v.length) bad.push(`${name} axe: ${v.join(', ')}`);
    if (w < 600) { const s = await t.small(); if (s.length) bad.push(`${name} small targets: ${s.slice(0, 3).map((x) => `${x.n}=${x.h}px`).join(', ')}`); }
  }
  await addFlow(); await t.page.fill('#sw-name', 'Kubernetes'); await t.page.keyboard.press('Enter'); await t.wait(250);
  const v = await t.axe(); if (v.length) bad.push(`add flow axe: ${v.join(', ')}`);
  const o = await t.overflow(); if (o > 0) bad.push(`add flow scrolls sideways by ${o}px`);
  if (w < 600) { const s = await t.small(); if (s.length) bad.push(`add flow small targets: ${s.slice(0, 3).map((x) => `${x.n}=${x.h}px`).join(', ')}`); }
  assert.deepStrictEqual(bad, [], bad.join(' | '));
});
both('a11y-menus-and-sections-announce-state', async (t) => {
  await t.go('software');
  const h = await t.page.$eval('[data-act="swHist"]', (b) => b.getAttribute('aria-expanded'));
  assert.strictEqual(h, 'false', 'History button has aria-expanded');
  await t.click('[data-act="swHist"]'); assert.strictEqual(await t.page.$eval('[data-act="swHist"]', (b) => b.getAttribute('aria-expanded')), 'true');
  await t.go('agents');
  assert.strictEqual(await t.count('.lib-tabs [aria-pressed]'), 3, 'tabs say which is chosen');
  assert.strictEqual(await t.count('main [role=status], main .vh'), await t.count('main [role=status], main .vh'), 'sanity');
});

/* ---------- Seeded control ---------- */
check('control-approver-sees-fix-button', (b) => session(b, 1280, async (t) => {
  await t.ctl('user', 'bob'); await t.go('software');
  assert.strictEqual(await t.count('[data-act="useNewAddress"]'), 1, 'seeded control: Bob has the fix button');
}), { expectedFail: true });

/* ---------- P0 stays green ---------- */
check('p0-gate-still-passes', () => {
  const r = spawnSync('node', [path.join(__dirname, 'gates-p0.cjs'), file], { cwd: here, encoding: 'utf8', maxBuffer: 1 << 26 });
  const tail = (r.stdout || '').trim().split('\n').slice(-3).join(' | ');
  assert.strictEqual(r.status, 0, `gates-p0 failed: ${tail}`);
  console.log(`              gates-p0: ${(r.stdout || '').trim().split('\n').pop()}`);
});


/* Fix round A, item 12: the moved project is one item, read by Needs you, the tab count and the watchlist alike. */
both('wl-langserve-in-needs-you', async (t) => {
  const badge = async () => +(await t.page.$$eval('.badge[data-val="needs-n"]', (els) => (els[0] ? els[0].textContent.replace(/\D/g, '') : '0')));
  await t.go('workflows');
  const before = await badge();
  const needs = await t.page.innerText('#needs-h >> xpath=..');
  assert(needs.includes('GitHub can’t find langchain-ai/langserve. It moved to langchain-ai/langchain.'), `Needs you has the moved project: ${needs.slice(0, 200)}`);
  assert.strictEqual(+needs.match(/Needs you\s*(\d+)/)[1], before, 'the tab count and Needs you agree');
  await t.page.$eval('#needs-h >> xpath=.. >> [data-act="useNewAddress"]', (b) => b.click()); await t.wait(300);
  assert.strictEqual(await badge(), before - 1, 'fixing it from Workflows drops the count by one');
  await t.go('software');
  assert.strictEqual(await t.count('[data-act="useNewAddress"]'), 0, 'and the watchlist no longer asks');
  await t.ctl('user', 'bob'); await t.go('home');
  assert(!(await t.text()).includes('langserve'), 'an Approver who is not an Operator is not asked to fix it');
});

(async () => {
  const browser = await chromium.launch();
  for (const c of checks) {
    if (process.env.ONLY && !c.name.includes(process.env.ONLY)) continue;
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
