/* Gate checks for the P1b slice of the AI-native redesign: Workflows (spec 8), the workflow page (9) and the run page (10).
   Usage: node docs/design/ai-native-redesign/checks/gates-p1b.cjs <prototype.html>
   Prints one line per named check at 1280 px and 390 px, re-runs gates-p0.cjs, and exits non-zero on any failure.
   One control check is seeded to fail, to prove the gate can fail; it is reported as an expected failure. */
const path = require('path');
const fs = require('fs');
const assert = require('assert');
const { execFileSync, spawnSync } = require('child_process');

const file = path.resolve(process.argv[2] || path.join(__dirname, '..', 'prototype.html'));
const here = path.resolve(__dirname, '..', '..', '..', '..');
const common = (() => { try { return path.dirname(path.resolve(here, execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: here }).toString().trim())); } catch (e) { return here; } })();
const { chromium } = require(require.resolve('playwright', { paths: [path.join(here, 'portal'), path.join(common, 'portal')] }));
const url = `file://${file}`;
const source = fs.readFileSync(file, 'utf8');

const EX_SUMMARY = 'Every Friday, sum up the tickets we closed this week';
const EX_COMPARE = 'Every Monday, compare last week’s new tickets with the week before';
const STATUS_WORDS = ['On', 'Waiting for a yes', 'Stopped', 'Paused', 'No answer'];

const results = [];
const consoleErrors = [];
const record = (name, err, expectedFail) => {
  const ok = !err;
  const status = expectedFail ? (ok ? 'FAIL' : 'EXPECTED-FAIL') : ok ? 'PASS' : 'FAIL';
  results.push({ name, status });
  console.log(`${status.padEnd(13)} ${name}${err ? `: ${String(err.message || err).split('\n')[0]}` : ''}${expectedFail && ok ? ': the seeded control passed, so the gate cannot fail' : ''}`);
};

async function session(browser, width, body) {
  const phone = width < 900;
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce', colorScheme: 'light', hasTouch: phone, isMobile: phone });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror @${width}: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`console @${width}: ${m.text()}`); });
  await page.goto(url);
  await page.waitForTimeout(250);
  const t = {
    page,
    width,
    wait: (ms) => page.waitForTimeout(ms),
    text: () => page.innerText('main'),
    has: async (sel) => (await page.$(sel)) !== null,
    count: (sel) => page.$$eval(sel, (els) => els.length).catch(() => 0),
    click: async (sel) => { await page.click(sel); await page.waitForTimeout(220); },
    go: async (tab) => { await page.click(`${phone ? '.tab' : '.nav-a'}[data-arg="${tab}"]`); await page.waitForTimeout(260); },
    openTest: async () => { if (!(await page.$('.testctl-panel'))) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    closeTest: async () => { if (await page.$('.testctl-panel')) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    ctl: async (act, arg) => { await t.openTest(); await page.click(`.testctl [data-act="${act}"][data-arg="${arg}"]`); await page.waitForTimeout(260); await t.closeTest(); },
    sim: async (label) => { await t.openTest(); await page.$eval(`.testctl button:has-text("${label}")`, (b) => b.click()); await page.waitForTimeout(260); await t.closeTest(); },
    ask: async (text) => { await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await page.waitForTimeout(700); },
    workflow: async (id) => { await t.go('workflows'); await t.click(`[data-act="workflow"][data-arg="${id}"]`); },
    run: async (id) => { await page.click(`[data-act="run"][data-arg="${id}"], [data-act="watch"][data-arg="${id}"]`); await page.waitForTimeout(400); },
    focused: () => page.evaluate(() => { const a = document.activeElement; return a ? `${a.tagName.toLowerCase()}${a.id ? `#${a.id}` : ''}${a.dataset && a.dataset.act ? `[${a.dataset.act}]` : ''}` : ''; }),
    noSideScroll: async (label) => { const w = await page.evaluate(() => document.scrollingElement.scrollWidth); assert(w <= width, `${label} scrolls sideways at ${width}: ${w}`); },
    /* On a phone every visible control in main is at least 44 px tall. A row's title link counts by its row. */
    targets: async (label) => {
      if (!phone) return;
      const small = await page.$$eval('main button, main a, main summary, main input, main select', (els) => els.filter((el) => el.getClientRects().length).map((el) => { const r = (el.classList.contains('rcard-link') ? el.closest('li, .row') : el).getBoundingClientRect(); return [el.textContent.trim().slice(0, 30) || el.getAttribute('aria-label') || el.tagName, Math.round(r.height)]; }).filter(([, h]) => h < 44));
      assert.deepStrictEqual(small, [], `${label}: controls under 44 px: ${small.map(([n, h]) => `${n} ${h}`).join(', ')}`);
    },
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
const both = (name, fn, opts) => { for (const width of [1280, 390]) check(`${name}@${width}`, (browser) => session(browser, width, fn), opts); };
const inOrder = (text, parts) => { let at = -1; for (const p of parts) { const i = text.indexOf(p, at + 1); assert(i > at, `${p} missing or out of order`); at = i; } };

check('no-long-dashes', () => {
  const bad = source.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => /[—–]/.test(l)).map(([i]) => i);
  assert.deepStrictEqual(bad, [], `long dashes on lines ${bad.join(', ')}`);
});
check('five-button-row-gone', () => { assert(!/class="rowacts"/.test(source), 'the row of five buttons is gone'); });

/* Spec 8: section order, each only with items, row shape, no faces, search behind a button. */
both('wf-sections-in-order', async (t) => {
  await t.ask(EX_SUMMARY);
  await t.click('[data-act="newChat"]');
  await t.turnOn(EX_COMPARE);
  await t.click('[data-act="testRun"]'); await t.wait(300);
  await t.go('workflows');
  await t.click('[data-act="report"]'); await t.wait(200); await t.click('[data-act="sendReport"]'); await t.wait(200); await t.page.keyboard.press('Escape'); await t.wait(200);
  const heads = await t.page.$$eval('main h2[id], main section > h2', (els) => els.map((e) => e.textContent.replace(/\d+/g, '').trim()));
  const want = ['Needs you', 'Drafts', 'Waiting on others', 'Following up', 'All workflows'];
  assert.deepStrictEqual(heads.filter((h) => want.includes(h)), want, `sections: ${heads.join(' | ')}`);
  const draft = await t.page.locator('.draft-row').first().innerText();
  assert(/Needs .*Jira project/.test(draft), `draft names what it needs: ${draft}`);
  assert(draft.includes('Resume') && draft.includes('Discard'), 'draft has Resume and Discard');
  await t.noSideScroll('workflows'); await t.targets('workflows');
});
both('wf-sections-only-with-items', async (t) => {
  await t.go('workflows');
  const alice = await t.text();
  for (const h of ['Drafts', 'Waiting on others', 'Following up']) assert(!alice.includes(h), `${h} hidden when empty`);
  await t.ctl('user', 'bob'); await t.go('workflows');
  const bob = await t.text();
  assert(bob.includes('Needs you'), 'Bob sees Needs you on Workflows');
  assert(!bob.includes('Drafts'), 'Bob has no Drafts');
  await t.ctl('day', 'one'); await t.go('workflows');
  assert((await t.text()).includes('Operators set up workflows, and you approve their changes.'), 'Approver-only empty text');
  await t.ctl('user', 'alice'); await t.go('workflows');
  const day1 = await t.text();
  assert(day1.includes('Nothing here yet') && day1.includes('Ask the Planner on Home, and your first workflow shows up here.'), 'Operator empty text');
  assert(!day1.includes('Needs you'), 'no Needs you on day one');
});
both('wf-row-shape', async (t) => {
  await t.go('workflows');
  const rows = await t.page.$$eval('.wf-row', (els) => els.map((r) => ({
    name: !!r.querySelector('h2'), purpose: !!r.querySelector('.wf-main p'), pills: r.querySelectorAll('.pill').length,
    pill: (r.querySelector('.pill') || {}).textContent, next: !!r.querySelector('.wf-next'), acts: r.querySelectorAll('.wf-act button').length, faces: r.querySelectorAll('.faces, .face').length,
  })));
  assert(rows.length >= 3, `rows: ${rows.length}`);
  for (const r of rows) {
    assert(r.name && r.purpose && r.next, `row has name, purpose and next run: ${JSON.stringify(r)}`);
    assert.strictEqual(r.pills, 1, `one status pill: ${JSON.stringify(r)}`);
    assert(STATUS_WORDS.some((w) => r.pill.trim() === w), `status in the spec's words: ${r.pill}`);
    assert(r.acts <= 1, `at most one action: ${JSON.stringify(r)}`);
    assert.strictEqual(r.faces, 0, 'no agent faces in the list');
  }
  assert.strictEqual(await t.count('.wf-list .btn.primary'), 0, 'the list repeats no main button that Needs you already offers');
  assert.strictEqual(await t.count('main .btn.primary'), 1, 'one main button on the page');
});
both('wf-search-behind-button', async (t) => {
  await t.go('workflows');
  assert(!(await t.has('#find-workflows')), 'search hidden by default');
  assert(!(await t.has('[data-act="filter"]')), 'filters hidden by default');
  const btn = t.page.locator('[data-act="findOpen"]');
  assert.strictEqual(await btn.getAttribute('aria-expanded'), 'false', 'button says closed');
  assert.strictEqual(await btn.getAttribute('aria-controls'), 'findbar-workflows', 'button names the bar');
  await t.click('[data-act="findOpen"]');
  assert(await t.has('#findbar-workflows #find-workflows'), 'search box shown');
  assert.strictEqual(await t.count('[data-act="filter"]'), 3, 'All, Stopped and Paused shown');
  assert.strictEqual(await t.focused(), 'input#find-workflows', 'focus moves to the box');
  await t.targets('workflows with search open');
  await t.click('[data-act="filter"][data-arg="stopped"]');
  assert.strictEqual(await t.count('.wf-row'), 2, 'Stopped filter keeps the two stopped workflows');
  await t.click('[data-act="findOpen"]');
  assert(!(await t.has('#find-workflows')), 'search hidden again');
  assert.strictEqual(await t.count('.wf-row'), 3, 'closing clears the filter');
  assert.strictEqual(await t.focused(), 'button[findOpen]', 'focus returns to the button');
});
check('wf-n8n-start-planned-only', async (browser) => session(browser, 1280, async (t) => {
  await t.go('workflows');
  assert(!(await t.text()).includes('Start in n8n'), 'Start in n8n hidden by default');
  await t.ctl('preview', 'on'); await t.go('workflows');
  assert.strictEqual(await t.page.locator('.n8n-start .tag.planned').count(), 1, 'shown and tagged with Planned features');
}));

/* Spec 9: the page order, the banner, Schedule and Approval with Change, the menu, Technical details. */
both('wp-order-and-banner', async (t) => {
  await t.workflow('issues');
  const text = await t.text();
  inOrder(text, ['Stopped', 'Morning new-ticket check', 'Finds the tickets created', 'Stopped today at 8:00. Jira didn’t answer, and it’s working again now.', 'Schedule', 'Every weekday at 8:00, Singapore time', 'Approval', 'any Approver except you', 'Recent activity', 'Technical details']);
  assert.strictEqual(await t.page.locator('.banner .btn.primary').innerText(), 'Retry the run', 'the banner carries the one primary action');
  assert.strictEqual(await t.count('main .btn.primary'), 1, 'one primary action on the page');
  assert((await t.page.locator('.factrows [data-act="editSched"]').innerText()).includes('Change'), 'Schedule has Change');
  assert(!(await t.has('.rowacts')), 'no row of buttons');
  await t.noSideScroll('workflow page'); await t.targets('workflow page');
  await t.click('[data-act="retryIssues"]'); await t.wait(400);
  await t.workflow('issues');
  assert(/On\. Next run Wed 28 Oct, 8:00\./.test(await t.text()), 'after the retry the banner says On with the next run');
  assert.strictEqual(await t.count('.banner .btn'), 0, 'a workflow that is on has no banner button');
  await t.workflow('nudge');
  assert.strictEqual(await t.page.locator('.banner .btn.primary').innerText(), 'Report to support', 'the platform-bug stop offers Report to support');
});
both('int-one-troubleshooter-table', async (t) => {
  for (const [id, name] of [['issues', 'Morning new-ticket check'], ['nudge', 'Weekly closed-ticket summary']]) {
    await t.go('home'); if (await t.has('[data-act="newChat"]')) await t.click('[data-act="newChat"]');
    await t.ask(`Why did ${name} stop?`);
    const planner = await t.page.$$eval('.thread .pcard.why .qa dd', (els) => els.map((e) => e.textContent.trim()));
    const plannerAct = await t.page.locator('.thread .pcard.why .btn.primary').innerText();
    await t.workflow(id); await t.run(id);
    const run = await t.page.$$eval('#decision .qa dd', (els) => els.map((e) => e.textContent.trim()));
    const runAct = await t.page.locator('#decision .btn.primary').innerText();
    assert.deepStrictEqual(run, planner, `${id}: the run page and the Planner give the same four answers`);
    assert.strictEqual(runAct, plannerAct, `${id}: the same primary action in both places`);
  }
});
both('int-one-action-per-thing-on-workflows', async (t) => {
  await t.go('workflows');
  assert.strictEqual(await t.count('[data-act="retryIssues"]'), 1, 'one Retry the run on the page');
  assert.strictEqual(await t.count('[data-act="report"]'), 1, 'one Report to support on the page');
  assert.strictEqual(await t.count('.wf-row[data-flip="wf:issues"] .wf-act button'), 0, 'the listed item keeps its pill and drops the repeated action');
  assert.strictEqual(await t.page.locator('.wf-row[data-flip="wf:issues"] .pill').innerText(), 'Stopped', 'the status pill stays');
});
both('int-idle-pill-says-on', async (t) => {
  await t.go('workflows');
  await t.click('[data-act="retryIssues"]'); await t.wait(400);
  await t.go('workflows');
  const pills = await t.page.$$eval('.wf-row .pill', (els) => els.map((e) => e.textContent.trim()));
  assert(pills.includes('On'), `a switched-on workflow between runs says On: ${pills.join(', ')}`);
  assert(!pills.includes('Running'), 'Running is only for a run in progress');
});
both('int-menu-arrow-keys', async (t) => {
  await t.workflow('issues');
  await t.page.focus('[data-act="menu"]'); await t.page.keyboard.press('Enter'); await t.wait(200);
  const at = () => t.page.evaluate(() => [...document.querySelectorAll('.menu [role="menuitem"]')].indexOf(document.activeElement));
  const n = await t.count('.menu [role="menuitem"]');
  assert.strictEqual(await at(), 0, 'opens on the first item');
  await t.page.keyboard.press('ArrowDown'); assert.strictEqual(await at(), 1, 'Down moves to the next item');
  await t.page.keyboard.press('End'); assert.strictEqual(await at(), n - 1, 'End goes to the last item');
  await t.page.keyboard.press('ArrowDown'); assert.strictEqual(await at(), 0, 'Down from the last wraps to the first');
  await t.page.keyboard.press('ArrowUp'); assert.strictEqual(await at(), n - 1, 'Up from the first wraps to the last');
  await t.page.keyboard.press('Home'); assert.strictEqual(await at(), 0, 'Home goes to the first item');
  await t.page.keyboard.press('Escape'); await t.wait(200);
  assert.strictEqual(await t.focused(), 'button[menu]', 'Escape still returns focus to the button');
});
both('wp-more-actions-menu', async (t) => {
  await t.workflow('issues');
  const btn = t.page.locator('[data-act="menu"]');
  assert.strictEqual(await btn.getAttribute('aria-expanded'), 'false', 'menu closed');
  assert.strictEqual(await btn.getAttribute('aria-controls'), 'menu-issues', 'button names the menu');
  assert(!(await t.has('.menu')), 'menu not drawn while closed');
  await t.click('[data-act="menu"]');
  assert.strictEqual(await btn.getAttribute('aria-expanded'), 'true', 'menu open');
  const items = await t.page.$$eval('#menu-issues[role="menu"] > *', (els) => els.map((e) => (e.tagName === 'HR' ? '---' : e.textContent.trim())));
  assert.deepStrictEqual(items, ['Run now', 'Pause', 'Change schedule', 'Open in n8n', '---', 'Delete'], `items: ${items.join(' | ')}`);
  assert(await t.has('#menu-issues [role="menuitem"].danger:last-child'), 'Delete is last and red');
  assert((await t.focused()).startsWith('button[menuPick]'), 'focus moves into the menu');
  await t.page.keyboard.press('Escape'); await t.wait(200);
  assert(!(await t.has('.menu')), 'Escape closes the menu');
  assert.strictEqual(await t.focused(), 'button[menu]', 'focus returns to the button');
  await t.click('[data-act="menu"]');
  await t.page.mouse.click(10, 400); await t.wait(200);
  assert(!(await t.has('.menu')), 'a click outside closes the menu');
  await t.click('[data-act="menu"]'); await t.click('[data-act="menuPick"][data-arg="pause:issues"]');
  const paused = await t.text();
  assert(paused.includes('Paused') && paused.includes('won’t run until you resume it'), 'Pause pauses it, with the banner saying so');
  assert.strictEqual(await t.page.locator('.banner .btn.primary').innerText(), 'Resume', 'Resume is the one action while paused');
  await t.click('[data-act="menu"]');
  assert.strictEqual(await t.page.locator('#menu-issues [role="menuitem"]').nth(1).innerText(), 'Resume', 'menu offers Resume while paused');
  await t.click('[data-act="menuPick"][data-arg="resume:issues"]');
  await t.click('[data-act="menu"]'); await t.click('[data-act="menuPick"][data-arg="editSched:issues"]');
  assert.strictEqual(await t.focused(), 'select#sf-freq', 'Change schedule opens the editor and focuses it');
  await t.click('[data-act="cancelSched"]');
  await t.click('[data-act="menu"]'); await t.click('[data-act="menuPick"][data-arg="askDelete:issues"]');
  const dlg = await t.page.innerText('[role="alertdialog"]');
  assert(dlg.includes('Delete Morning new-ticket check?') && dlg.includes('past runs and their records stay') && dlg.includes('undo'), `delete names what is lost: ${dlg}`);
  await t.click('[data-act="confirmDelete"]');
  assert(!(await t.text()).includes('Morning new-ticket check'), 'deleted from the list');
  assert(await t.has('.toast [data-act="undoDelete"]'), 'Undo in the message');
  await t.click('.toast [data-act="undoDelete"]');
  assert((await t.text()).includes('Morning new-ticket check'), 'Undo puts it back');
});
both('wp-approval-rule', async (t) => {
  await t.workflow('issues');
  let text = await t.text();
  assert(text.includes('Each run’s ticket waits for a yes from any Approver except you.'), 'the owner reads "except you"');
  assert(!/backup|Change who approves|stops waiting/i.test(text), 'no named-Approver wording by default');
  await t.ctl('user', 'bob'); await t.workflow('issues');
  text = await t.text();
  assert(text.includes('Any Approver except Alice can say yes.'), 'another reader sees the owner named');
  assert(!(await t.has('[data-act="menu"]')), 'an Approver has no More actions');
  assert(!(await t.has('[data-act="editSched"]')), 'an Approver has no Change');
  await t.ctl('preview', 'on'); await t.workflow('issues');
  assert((await t.page.locator('.factrows .tag.planned').count()) >= 1, 'named Approvers tagged Planned');
});
both('wp-technical-details', async (t) => {
  await t.workflow('issues');
  const d = t.page.locator('details.tech');
  assert.strictEqual(await d.getAttribute('open'), null, 'Technical details closed by default');
  assert(!(await t.text()).includes('Reads Jira'), 'steps hidden until opened');
  await t.click('details.tech summary');
  const text = await t.page.innerText('details.tech');
  inOrder(text, ['Steps', 'Reads Jira', 'No system access', 'Changes data, waits for a yes', 'Agents and tools', 'Planner', 'Jira reader', 'Search Jira', 'In n8n', 'Change history']);
  await t.noSideScroll('technical details'); await t.targets('technical details');
});
both('wp-recent-activity-opens-run', async (t) => {
  await t.workflow('issues');
  const rows = await t.page.$$eval('.panel:has(h2:text("Recent activity")) .rows > *', (els) => els.map((e) => [e.tagName, e.textContent.trim().slice(0, 12)]));
  assert.strictEqual(rows[0][0], 'BUTTON', `newest run first, as a button: ${JSON.stringify(rows)}`);
  assert(rows[0][1].startsWith('Today'), `newest first: ${rows[0][1]}`);
  await t.click('.panel [data-act="watch"][data-arg="issues"]'); await t.wait(400);
  assert((await t.text()).includes('Stopped at Find new tickets'), 'opens the run page');
});

/* Spec 10: the default run page, the detail on request, the four answers, the approval panel and its safety rules. */
both('run-default-and-detail', async (t) => {
  await t.ctl('user', 'bob');
  await t.run('sw');
  inOrder(await t.text(), ['3 tickets are waiting for a yes', 'Waiting for a yes', 'Started', 'Approval gate', 'What will change']);
  assert((await t.count('.stage .st')) >= 6, 'the station strip shows');
  assert((await t.count('.stage .st-who .face, .stage .st-who .pav')) >= 4, 'faces on the strip');
  assert.strictEqual(await t.count('.cmsg-bubble'), 0, 'conversation hidden by default');
  assert(!(await t.has('[data-act="replay"]')) && !(await t.has('[data-act="speed"]')), 'no replay controls by default');
  assert(await t.has('#decision'), 'the decision is on the page');
  const btn = t.page.locator('[data-act="runDetail"]');
  assert.strictEqual(await btn.getAttribute('aria-expanded'), 'false', 'detail closed');
  assert.strictEqual(await btn.getAttribute('aria-controls'), 'run-detail', 'button names the detail');
  await t.noSideScroll('run page'); await t.targets('run page');
  await t.click('[data-act="runDetail"]');
  assert.strictEqual(await btn.getAttribute('aria-expanded'), 'true', 'detail open');
  assert((await t.count('#run-detail .cmsg-bubble')) >= 3, 'the agents’ conversation shows');
  assert((await t.page.innerText('#run-detail')).includes('I read each tool’s releases on GitHub'), 'tool results in the conversation');
  assert(await t.has('#run-detail [data-act="replay"]') && (await t.count('#run-detail [data-act="speed"]')) === 3, 'replay controls inside the detail');
  await t.click('[data-act="approve"][data-arg="sw"]'); await t.wait(400);
  assert.strictEqual(await btn.getAttribute('aria-expanded'), 'true', 'stays open after a decision on this visit');
  await t.noSideScroll('run detail'); await t.targets('run detail');
  await t.go('software'); await t.page.goBack(); await t.wait(400);
  assert(await t.has('.stage'), 'Back returns to the run');
  assert.strictEqual(await t.page.locator('[data-act="runDetail"]').getAttribute('aria-expanded'), 'false', 'closed again on a new visit');
});
both('run-stopped-four-answers', async (t) => {
  await t.workflow('issues'); await t.run('issues');
  const qs = await t.page.$$eval('#decision .qa dt', (els) => els.map((e) => e.textContent.trim()));
  assert.deepStrictEqual(qs, ['What happened', 'What was affected', 'Can it be fixed safely', 'What to do'], `answers: ${qs.join(' | ')}`);
  assert.strictEqual(await t.page.locator('#decision .btn.primary').innerText(), 'Retry the run', 'Retry is on the run page');
  await t.click('#decision [data-act="retryIssues"]'); await t.wait(600);
  assert((await t.text()).includes('Done, nothing new today'), 'the retry runs and finishes');
  await t.workflow('nudge'); await t.run('nudge');
  assert.strictEqual(await t.page.locator('#decision .btn.primary').innerText(), 'Report to support', 'a platform bug offers Report to support');
  await t.click('#decision [data-act="report"]'); await t.wait(200); await t.click('[data-act="sendReport"]'); await t.wait(200); await t.page.keyboard.press('Escape'); await t.wait(200);
  assert((await t.page.innerText('#decision')).includes('Case SUP-1042'), 'the case shows on the run page');
  for (let i = 0; i < 3; i += 1) await t.sim('Support moves case');
  assert.strictEqual(await t.page.locator('#decision .btn.primary').innerText(), 'Retry the run', 'after the fix, Retry the run');
  await t.click('#decision [data-act="retryNudge"]'); await t.wait(600);
  assert((await t.text()).includes('1 ticket is waiting for a yes'), 'the retried run waits for a yes');
  assert.strictEqual(await t.count('[data-act="approve"]'), 0, 'Alice retried it, so Alice cannot approve');
  assert((await t.text()).includes('another Approver must decide'), 'her part says why');
  await t.ctl('user', 'bob'); await t.go('workflows'); await t.run('nudge');
  assert.strictEqual(await t.count('[data-act="approve"][data-arg="nudge"]'), 1, 'Bob can approve the retried run');
  await t.click('[data-act="approve"][data-arg="nudge"]'); await t.wait(500);
  assert((await t.text()).includes('MOCK-34'), 'the approved ticket is written');
});
both('run-approval-panel-parts', async (t) => {
  await t.ctl('user', 'bob'); await t.run('sw');
  const panel = await t.page.innerText('#decision');
  inOrder(panel, ['What will change', '3 tickets will be created in Jira project MOCK', 'Upgrade Log4j core', 'Upgrade LangGraph', 'Upgrade FastAPI', 'Why', 'Version checker:', 'Ticket writer:', 'Who asked', 'set up by Carol', 'Carol’s schedule started', 'What happens', 'Nothing is written until you say yes. If you decline, nothing is written.', 'waits until one of them decides', 'Your part', 'You can decide because you didn’t set this up.']);
  assert(!/stops waiting|by \d+:\d\d|before the next run/.test(panel), 'no stop time under today’s rule');
  assert((await t.count('#decision a[href*="github.com"]')) >= 6, 'links to the evidence');
  const btns = await t.page.$$eval('#decision .btns .btn', (els) => els.map((e) => e.textContent.trim()));
  assert.deepStrictEqual(btns, ['Approve', 'Decline'], `buttons: ${btns.join(' | ')}`);
  await t.click('[data-act="decline"][data-arg="sw"]'); await t.wait(400);
  assert((await t.text()).includes('Declined, nothing was written'), 'Decline writes nothing');
});
both('run-self-never-offered-approve', async (t) => {
  await t.turnOn(EX_SUMMARY);
  await t.click('[data-act="testRun"]'); await t.wait(400);
  assert.strictEqual(await t.count('[data-act="approve"]'), 0, 'Alice has no Approve on her own test run');
  assert.strictEqual(await t.count('[data-act="decline"]'), 0, 'and no Decline');
  const part = await t.page.innerText('#decision');
  assert(part.includes('You set this up and started this run, so another Approver must decide.'), `her part: ${part.match(/Your part[^\n]*\n[^\n]*/)}`);
  assert((await t.text()).includes('Test run'), 'marked as a test run');
  await t.ctl('user', 'bob'); await t.go('workflows'); await t.run('conf');
  assert.strictEqual(await t.count('[data-act="approve"][data-arg="conf"]'), 1, 'Bob, who did not set it up, can decide');
  assert((await t.page.innerText('#decision')).includes('You can decide because you didn’t set this up.'), 'his part says so');
});
check('control-self-approve-offered', async (browser) => session(browser, 1280, async (t) => {
  await t.turnOn(EX_SUMMARY);
  await t.click('[data-act="testRun"]'); await t.wait(400);
  assert.strictEqual(await t.count('[data-act="approve"]'), 1, 'seeded control: Approve offered to the person whose run it is');
}), { expectedFail: true });
check('run-no-loops-under-reduced-motion', async (browser) => session(browser, 1280, async (t) => {
  await t.workflow('issues'); await t.click('.panel [data-act="watch"][data-arg="issues"]'); await t.wait(300);
  const loops = await t.page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running' && a.effect && a.effect.getTiming().iterations === Infinity).length);
  assert.strictEqual(loops, 0, `looping animations under reduced motion: ${loops}`);
}));
check('keyboard-reaches-menu-and-detail', async (browser) => session(browser, 1280, async (t) => {
  await t.workflow('issues');
  await t.page.focus('[data-act="menu"]'); await t.page.keyboard.press('Enter'); await t.wait(200);
  assert(await t.has('.menu'), 'Enter opens the menu');
  const ring = await t.page.evaluate(() => { const s = getComputedStyle(document.activeElement); return s.outlineStyle !== 'none' || s.backgroundColor !== 'rgba(0, 0, 0, 0)'; });
  assert(ring, 'the focused menu item is visibly marked');
  await t.page.keyboard.press('Tab'); await t.page.keyboard.press('Enter'); await t.wait(200);
  assert((await t.text()).includes('Paused'), 'the second item, Pause, works from the keyboard');
  await t.click('.panel [data-act="watch"][data-arg="issues"]'); await t.wait(300);
  await t.page.focus('[data-act="runDetail"]'); await t.page.keyboard.press('Enter'); await t.wait(200);
  assert((await t.count('.cmsg-bubble')) >= 1, 'Enter opens the detail');
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
  const p0 = spawnSync(process.execPath, [path.join(__dirname, 'gates-p0.cjs'), file], { encoding: 'utf8' });
  const p0line = (p0.stdout || '').trim().split('\n').pop();
  record(`gates-p0 (${p0line})`, p0.status === 0 ? null : new Error((p0.stdout || '').split('\n').filter((l) => l.startsWith('FAIL')).join(' | ') || p0.stderr));
  const failed = results.filter((r) => r.status === 'FAIL');
  console.log(`\n${results.length - failed.length} passed, ${failed.length} failed, ${results.filter((r) => r.status === 'EXPECTED-FAIL').length} expected failure`);
  process.exit(failed.length ? 1 : 0);
})();
