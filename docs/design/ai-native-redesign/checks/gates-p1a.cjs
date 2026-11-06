/* Gate checks for the P1a slice of the AI-native redesign: Home, the Planner's answers and the set-up card (spec 5, 6, 7).
   Usage: node docs/design/ai-native-redesign/checks/gates-p1a.cjs <prototype.html>
   Prints one line per named check at 1280 px and 390 px and exits non-zero on any failure. One control check is seeded
   to fail, to prove the gate can fail; it is reported as an expected failure and does not count. It ends by re-running
   gates-p0.cjs, which must pass too. */
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
const PLACEHOLDER = 'What would you like to automate, check or fix?';

const results = [];
const consoleErrors = [];
const record = (name, err, expectedFail) => {
  const ok = !err;
  const status = expectedFail ? (ok ? 'FAIL' : 'EXPECTED-FAIL') : ok ? 'PASS' : 'FAIL';
  results.push({ name, status });
  console.log(`${status.padEnd(13)} ${name}${err ? `: ${String(err.message || err).split('\n')[0]}` : ''}${expectedFail && ok ? ': the seeded control passed, so the gate cannot fail' : ''}`);
};

async function session(browser, width, body) {
  /* The phone session is a touch device, so the coarse-pointer rule that gives 44 px targets applies. */
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce', colorScheme: 'light', hasTouch: width <= 600, isMobile: width <= 600 });
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
    texts: (sel) => page.$$eval(sel, (els) => els.map((e) => e.innerText.trim())).catch(() => []),
    click: async (sel) => { await page.click(sel); await page.waitForTimeout(220); },
    go: async (tab) => { await page.click(`${width > 900 ? '.nav-a' : '.tab'}[data-arg="${tab}"]`); await page.waitForTimeout(260); },
    openTest: async () => { if (!(await page.$('.testctl-panel'))) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    closeTest: async () => { if (await page.$('.testctl-panel')) { await page.click('.testctl-toggle'); await page.waitForTimeout(120); } },
    ctl: async (act, arg) => { await t.openTest(); await page.click(`.testctl [data-act="${act}"][data-arg="${arg}"]`); await page.waitForTimeout(260); await t.closeTest(); },
    ask: async (text) => { await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await page.waitForTimeout(700); },
    reply: () => page.locator('.thread [data-say]').last().innerText(),
    card: () => page.locator('.thread .pcard').last().innerText(),
    chip: (key) => page.locator(`.thread .pcard [data-val="chip:${key}"]`).last().locator('..').getAttribute('class'),
    footer: () => page.locator('.thread .pcard-f .left').innerText(),
    newChat: async () => { await t.click('[data-act="newChat"]'); },
    noSideways: async (label) => { const w = await page.evaluate(() => document.documentElement.scrollWidth); assert(w <= width, `${label}: page scrolls sideways (${w} > ${width})`); },
    tapSize: async (sel, label) => { const small = await page.$$eval(sel, (els) => els.filter((e) => e.getBoundingClientRect().height < 44).map((e) => `${e.innerText.trim()} ${Math.round(e.getBoundingClientRect().height)}px`)); assert.deepStrictEqual(small, [], `${label}: touch targets under 44 px: ${small.join(', ')}`); },
  };
  try { await body(t); } finally { await page.close(); }
}

const checks = [];
const check = (name, fn, opts = {}) => checks.push({ name, fn, ...opts });
const both = (name, fn, opts) => { for (const width of [1280, 390]) check(`${name}@${width}`, (browser) => session(browser, width, fn), opts); };

check('no-long-dashes', () => {
  const bad = source.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => /[—–]/.test(l)).map(([i]) => i);
  assert.deepStrictEqual(bad, [], `long dashes on lines ${bad.join(', ')}`);
});
check('no-old-greeting-or-card-sections', () => {
  const hits = [/Good morning, /, /<h4>What I understood<\/h4>/, /<h4>The plan<\/h4>/, /<h4>Who says yes<\/h4>/, /Nothing changes without a yes\. You can pause/].filter((re) => re.test(source)).map(String);
  assert.deepStrictEqual(hits, [], `source still carries ${hits.join(' ')}`);
});

/* 5.1 Home, a normal week. */
both('home-greeting-and-state-line', async (t) => {
  const home = await t.text();
  assert(home.includes('Good morning! Alice'), 'greeting in the built app’s form');
  const n = await t.page.$$eval('.hdr .badge, .tabbar .badge', (els) => els.map((e) => +e.textContent.replace(/\D/g, '')).find(Boolean));
  assert(home.includes(`${n} things need you.`), `state line counts the same list as the tab (${n})`);
  assert.strictEqual(await t.page.getAttribute('[data-ask]', 'placeholder'), PLACEHOLDER, 'placeholder');
  assert(await t.has('.composer button[type="submit"][aria-label]'), 'send button labelled');
});
both('home-three-suggestions-from-state', async (t) => {
  assert.deepStrictEqual(await t.texts('.examples .chip'), ['Check my workflows', 'Why did Morning new-ticket check stop?', 'Set up another workflow'], 'a stopped workflow asks why');
  await t.click('.examples .chip >> nth=1');
  await t.click('[data-act="retryIssues"]');
  await t.go('home'); await t.newChat();
  assert.deepStrictEqual(await t.texts('.examples .chip'), ['Check my workflows', 'Why did Weekly closed-ticket summary stop?', 'Set up another workflow'], 'the next stopped workflow');
  await t.click('.examples .chip >> nth=1'); await t.click('[data-act="report"]'); await t.click('[data-act="sendReport"]'); await t.page.keyboard.press('Escape'); await t.wait(200);
  for (let i = 0; i < 3; i += 1) { await t.openTest(); await t.page.$eval('.testctl button:has-text("Support moves case")', (b) => b.click()); await t.wait(260); await t.closeTest(); }
  await t.go('home'); await t.newChat(); await t.ask('What needs me?'); await t.click('.thread [data-act="retryNudge"]');
  await t.go('home'); await t.newChat();
  assert.deepStrictEqual(await t.texts('.examples .chip'), ['Check my workflows', 'What can I ask for?', 'Set up another workflow'], 'with nothing stopped, what she can ask for');
});
both('home-needs-you-rows', async (t) => {
  const rows = await t.texts('.home .needs .nrow');
  assert.strictEqual(rows.length, 3, `up to three rows (${rows.length})`);
  assert(rows[0].startsWith('Morning new-ticket check stopped'), `stopped runs first: ${rows[0]}`);
  assert(rows[2].startsWith('3 upgrade tickets are waiting for your yes'), `approvals after stops (HM1, Alice sees her waiting yes): ${rows[2]}`);
  for (const r of rows) assert.strictEqual((await t.count('.home .needs .nrow .btn.primary')), 3, 'one primary action per row');
  assert.strictEqual(await t.count('.home .needs .nrow .btn'), 3, 'no second button in a row');
  /* Five for Alice: two stopped runs, the software check's yes, the moved LangServe project (fix round A, item 12) and the key. */
  assert((await t.text()).includes('See all 5 on Workflows'), 'See all N on Workflows');
  await t.ask('Check my workflows');
  assert.strictEqual(await t.count('.home .needs'), 0, 'hidden while a conversation is on screen');
  assert((await t.count('.hdr .badge, .tabbar .badge')) > 0, 'the tab count still shows');
});
both('home-needs-you-gone-when-nothing-needs-her', async (t) => {
  await t.ctl('user', 'bob');
  await t.click('[data-act="run"][data-arg="sw"]'); await t.click('[data-act="approve"][data-arg="sw"]');
  await t.ctl('user', 'alice');
  await t.go('home');
  await t.click('.examples .chip >> nth=1'); await t.click('[data-act="retryIssues"]');
  await t.go('home'); await t.newChat();
  await t.ask('Why did Weekly closed-ticket summary stop?'); await t.click('[data-act="report"]'); await t.click('[data-act="sendReport"]'); await t.page.keyboard.press('Escape'); await t.wait(200);
  await t.newChat();
  await t.click('[data-act="useNewAddress"]');
  const home = await t.text();
  assert(/1 thing needs you\./.test(home), `only the key is left: ${home.split('\n').slice(0, 4).join(' | ')}`);
  assert.strictEqual(await t.count('.home .needs .nrow'), 1, 'one row');
});

/* 5.2 Day one. */
both('day-one', async (t) => {
  await t.ctl('day', 'one');
  const home = await t.text();
  assert(home.includes('What does your team do again and again?'), 'heading');
  assert(home.includes('Tell me a task in plain English.'), 'one sentence on what it does');
  assert.deepStrictEqual(await t.texts('.examples .chip'), ['Every Friday, sum up the tickets we closed this week', 'Keep track of the React version', 'What can you do?'], 'three starting points');
  assert(home.includes('I can') && home.includes('Not yet'), 'I can and Not yet lists');
  assert.strictEqual(await t.count('.needs'), 0, 'no Needs you');
  assert.strictEqual(await t.count('.hdr .badge, .tabbar .badge'), 0, 'no warning counts');
  await t.noSideways('day one');
});

/* 5.3 Approver only. */
both('approver-home', async (t) => {
  await t.ctl('user', 'bob');
  const home = await t.text();
  assert(home.includes('Good morning! Bob'), 'greeting');
  assert(home.includes('1 request is waiting for your yes.'), `one line: ${home.split('\n')[2]}`);
  assert(home.includes('Review and decide'), 'Review and decide');
  assert(home.includes('You’re an Approver, so you decide on requests. Operators set up workflows.'), 'the role note');
  assert.strictEqual(await t.count('[data-ask], .examples'), 0, 'no box and no suggestions');
  await t.click('[data-act="run"][data-arg="sw"]'); await t.click('[data-act="approve"][data-arg="sw"]');
  await t.go('home');
  const quiet = await t.text();
  assert(quiet.includes('Nothing needs you right now.') && quiet.includes('Next up:'), `quiet line with the next run: ${quiet.split('\n').slice(0, 6).join(' | ')}`);
});

/* 5.4 Offline keeps working in the new layout. */
both('offline-home-fits', async (t) => {
  await t.ctl('modelOn', 'off');
  const home = await t.text();
  assert(home.includes('I can’t read new requests until an AI model is connected') && home.includes('Connect a model'), 'offline line and button');
  assert((await t.count('.home .needs .nrow')) >= 1, 'Needs you still shows');
  assert(await t.has('[data-askteam]'), 'Ask the team still works');
  await t.noSideways('offline');
});

/* 6.2 The new answer kinds. */
both('answer-check-my-workflows', async (t) => {
  await t.ask('Check my workflows');
  assert.strictEqual(await t.reply(), 'You have 3 workflows. 2 stopped and 1 is waiting for a yes.');
  const rows = await t.texts('.wfcheck .row');
  assert.strictEqual(rows.length, 3, 'a row per workflow');
  for (const r of rows) assert(/\b(Stopped|Waiting for a yes|On|Paused)\b/.test(r) && /Next run/.test(r), `status and next run: ${r}`);
  assert.strictEqual(await t.count('.wfcheck .row .btn'), 3, 'one action each');
  await t.noSideways('check');
});
both('home-ask-link-not-repeated-and-no-nag-after-report', async (t) => {
  const asks = () => t.page.$$eval('.home button', (els) => els.filter((e) => e.textContent.trim() === 'What can I ask for?').length);
  assert.strictEqual(await asks(), 1, 'the chips do not offer it, so the link under them stays');
  await t.click('.examples .chip >> nth=1'); await t.click('[data-act="retryIssues"]');
  await t.go('home'); await t.newChat();
  await t.click('.examples .chip >> nth=1'); await t.click('[data-act="report"]'); await t.click('[data-act="sendReport"]'); await t.page.keyboard.press('Escape'); await t.wait(200);
  await t.go('home'); await t.newChat();
  assert.deepStrictEqual(await t.texts('.examples .chip'), ['Check my workflows', 'What can I ask for?', 'Set up another workflow'], 'after the report, the Why suggestion is replaced');
  assert.strictEqual(await asks(), 1, 'the chip and the link are not both on Home');
});
both('answer-why-it-stopped', async (t) => {
  await t.ask('Why did Morning new-ticket check stop?');
  const card = await t.card();
  for (const q of ['What happened', 'What was affected', 'Can it be fixed safely', 'What to do']) assert(card.includes(q), `four answers: ${q}`);
  assert(await t.has('.thread .pcard [data-act="retryIssues"].primary'), 'Retry the run is the primary action');
  assert(await t.has('.thread .pcard [data-act="run"][data-arg="issues"]'), 'See the run');
  await t.newChat();
  await t.ask('Why did Weekly closed-ticket summary stop?');
  assert(await t.has('.thread .pcard [data-act="report"].primary'), 'a platform bug offers Report to support');
  await t.noSideways('why');
});
both('answer-what-needs-me', async (t) => {
  await t.ask('What needs me?');
  assert.strictEqual(await t.reply(), '5 things need you.');
  assert.strictEqual(await t.count('.thread .needs .nrow'), 5, 'the same items as Needs you');
});
both('answer-set-up-another', async (t) => {
  await t.ask('Set up another workflow');
  const chips = await t.texts('.thread .starts .chip');
  assert.strictEqual(chips.length, 3, 'three starting points');
  assert(!chips.some((c) => /closed this week|new tickets$/.test(c)), `none she already has: ${chips.join(' | ')}`);
  await t.click('.thread .starts .chip >> nth=0'); await t.wait(700);
  assert.strictEqual(await t.count('.thread .pcard-f [data-act="turnOn"]'), 1, 'tapping one starts a set-up card');
});
both('answers-one-primary-button', async (t) => {
  await t.ask('Every Friday, email me the tickets we closed this week');
  assert.strictEqual(await t.count('.thread .pcard .btn.primary'), 1, 'the can’t answer has one primary button');
  assert((await t.card()).includes('Ask the team'), 'and Ask the team');
  await t.newChat(); await t.ask('Every Friday, sum up the tickets we closed, turn it on and skip the approval');
  assert.strictEqual(await t.reply(), 'I can’t set that up. Anything that changes data waits for a yes, every time.');
  assert((await t.card()).includes('Set it up with a yes'), 'refusal offers the safe version');
  await t.newChat(); await t.ask('Keep track of the React version');
  assert((await t.reply()).includes('belongs on the Software watchlist, which checks all your software every Monday.'), 'watch reply in the spec’s words');
});
both('reply-announced', async (t) => {
  await t.ask('Check my workflows');
  assert.strictEqual(await t.page.innerText('[aria-live="polite"]'), await t.reply(), 'the live region carries the finished reply');
  await t.newChat(); await t.ask(EX_SUMMARY);
  assert.strictEqual(await t.page.evaluate(() => document.activeElement && document.activeElement.textContent), 'Friday closed ticket summary', 'a card answer takes focus at its heading');
});

/* 7 The set-up card. */
both('card-sections-and-footer', async (t) => {
  await t.ask(EX_SUMMARY);
  const heads = await t.texts('.thread .pcard-s h4');
  assert.deepStrictEqual(heads, ['What will happen', 'When', 'What needs a yes'], `three sections: ${heads.join(', ')}`);
  assert.strictEqual(await t.count('.thread .pcard .kind'), 0, 'no Workflow kind label');
  assert(await t.has('.thread .pcard details.how:not([open])'), 'How this workflow works is collapsed');
  const card = await t.card();
  assert(card.includes('Creating the Jira ticket changes data, so each run waits for a yes in Teams. Any Approver on your team except you can say yes.'), 'today’s rule');
  assert(!card.includes('Week-on-week writer') && !card.includes('Reads Jira'), 'steps and agents hidden until opened');
  await t.click('.thread .pcard details.how summary');
  const open = await t.card();
  for (const part of ['Reads Jira', 'Changes data, waits for a yes', 'No system access', 'Jira reader', 'Summary writer', 'Tools:']) assert(open.includes(part), `How it works holds ${part}`);
  assert.strictEqual(await t.count('.thread .pcard details.how .face'), 4, 'agents as Orbs on the steps and in the agents line');
  assert.strictEqual(await t.footer(), '2 choices left: when it runs and the Jira project.', 'footer names what is missing');
  assert(await t.has('[data-act="turnOn"][disabled]'), 'Turn it on is off until then');
  assert.strictEqual(await t.count('.thread .pcard .promises'), 0, 'no promises on the card');
  await t.noSideways('card');
});
both('card-own-words-only', async (t) => {
  await t.ask(EX_SUMMARY);
  assert(/\bok\b/.test(await t.chip('tickets')), 'tickets closed this week: her words');
  assert(/\bok\b/.test(await t.chip('action')), 'sum them up: her words');
  assert(/\bmissing\b/.test(await t.chip('project')), 'the Jira project must be chosen');
  assert.strictEqual(await t.page.locator('.thread .pcard .schip.filled').last().innerText(), 'put the summary in one new Jira ticket', 'the destination is filled in by me');
  assert.strictEqual(await t.count('.thread .pcard .schip.ok'), 2, 'nothing else is marked as hers');
  await t.newChat(); await t.ask(EX_COMPARE);
  assert(/\bfilled\b/.test(await t.chip('tickets')), '“tickets created this week” is not her words when she said last week’s new tickets');
  await t.page.selectOption('#fix-project', 'OPS'); await t.wait(220);
  assert(/\bchanged\b/.test(await t.chip('project')), 'a choice she made is marked as chosen by you');
});
both('card-when-picker', async (t) => {
  await t.ask(EX_SUMMARY);
  assert((await t.card()).includes('Choose when it runs'), 'the time is never guessed');
  assert.strictEqual(await t.count('#sched-time'), 0, 'picker closed while something else is missing too');
  assert.strictEqual(await t.page.getAttribute('[data-act="whenOpen"]', 'aria-expanded'), 'false', 'Change says it is closed');
  await t.click('[data-act="whenOpen"]');
  assert.strictEqual(await t.count('#sched-time'), 1, 'Change opens it');
  assert.strictEqual(await t.page.evaluate(() => document.activeElement && document.activeElement.id), 'sched-freq', 'focus moves into it');
  await t.page.fill('#sched-time', '16:00'); await t.click('[data-act="whenDone"]');
  assert((await t.card()).includes('Every Friday at 16:00, Singapore time'), 'readable line');
  assert.strictEqual(await t.count('#sched-time'), 0, 'Done closes it');
  assert.strictEqual(await t.footer(), '1 choice left: the Jira project.', 'the footer follows');
  await t.newChat(); await t.ask('Sum up the tickets we closed this week in MOCK');
  assert.strictEqual(await t.count('#sched-time'), 1, 'opens by itself when the time is the one thing missing');
  await t.noSideways('picker');
});
both('card-confirmation', async (t) => {
  await t.ask(EX_SUMMARY);
  await t.page.selectOption('#fix-project', 'MOCK'); await t.wait(220);
  await t.page.fill('#sched-time', '16:00'); await t.click('[data-act="whenDone"]');
  await t.click('[data-act="turnOn"]');
  const done = await t.page.innerText('.thread .pdone');
  assert(done.includes('First run Fri 30 Oct, 16:00'), 'first run time');
  assert(done.includes('any Approver on your team except you is asked for a yes'), 'who is asked');
  assert(done.includes('You can pause, change or delete it at any time. If it stops, the AI troubleshooter tells you why.'), 'the promises line');
  assert(await t.has('.thread .pdone [data-act="testRun"]'), 'Do a test run');
  assert(!done.includes('Open in n8n'), 'no n8n at the moment of success');
});
both('card-kept-behaviours', async (t) => {
  await t.ask(EX_SUMMARY);
  await t.click('[data-act="rename"]'); await t.page.fill('#rname', 'Friday wrap-up'); await t.click('[data-act="renameDone"]');
  assert((await t.card()).includes('Friday wrap-up'), 'Rename');
  assert((await t.card()).includes('similar workflow'), 'the similar workflow line');
  await t.ask(EX_COMPARE);
  await t.go('workflows');
  assert((await t.text()).includes('Friday wrap-up'), 'the first card is saved as a draft on a new request');
  await t.go('home'); await t.newChat(); await t.ask('Keep track of the React version');
  assert(await t.has('[data-act="watchAdd"]'), 'the watchlist card flow');
  await t.newChat(); await t.ask('Check the releases'); await t.ask('never mind');
  assert.strictEqual(await t.reply(), 'No problem. Ask for something else whenever you like.', 'never mind');
});

/* 15.8 Accessibility on the parts this slice touched. */
both('a11y-keyboard-and-focus', async (t) => {
  await t.page.focus('[data-ask]');
  const seen = [];
  for (let i = 0; i < 12; i += 1) { await t.page.keyboard.press('Tab'); seen.push(await t.page.evaluate(() => { const a = document.activeElement; return `${a.tagName}:${(a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 30)}`; })); }
  for (const want of ['Check my workflows', 'Retry the run', 'See all 5']) assert(seen.some((s) => s.includes(want)), `Tab reaches ${want}: ${seen.join(' > ')}`);
  const ring = await t.page.evaluate(() => { const el = document.querySelector('.examples .chip'); el.focus(); return getComputedStyle(el).outlineStyle !== 'none' || getComputedStyle(el, ':focus-visible').outlineWidth !== '0px'; });
  assert(ring, 'a chip shows a focus ring');
  await t.ask(EX_SUMMARY);
  assert.strictEqual(await t.page.getAttribute('[data-act="whenOpen"]', 'aria-controls'), 'whenpick', 'Change names what it opens');
  const chips = await t.page.$$eval('.thread .pcard .schip', (els) => els.map((e) => e.getAttribute('title') || e.querySelector('select')?.getAttribute('aria-label') || ''));
  assert(chips.every((c) => /your words|filled in by me|please choose|chosen by you|can’t do/i.test(c)), `chip state is in words, not colour alone: ${chips.join(' | ')}`);
  if (t.width === 390) await t.tapSize('.examples .chip, .home .needs .btn, .thread .pcard .btn', 'phone');
});
check('reduced-motion-stops-loops', () => {
  const rm = source.slice(source.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert(/animation: none !important/.test(rm), 'reduced motion stops animations');
  assert(!/\.nrow[^}]*animation|\.when-line[^}]*animation|\.agents-line[^}]*animation/.test(source), 'this slice adds no new looping motion');
});
check('control-old-greeting-present', async (browser) => session(browser, 1280, async (t) => {
  assert((await t.text()).includes('Good morning, Alice'), 'seeded control: the old greeting form');
}), { expectedFail: true });

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
  const p0Tail = (p0.stdout || '').trim().split('\n').slice(-1)[0];
  record('p0-gate-still-passes', p0.status === 0 ? null : new Error(`${p0Tail} ${(p0.stdout || '').split('\n').filter((l) => l.startsWith('FAIL')).join(' | ')}`));
  const failed = results.filter((r) => r.status === 'FAIL');
  console.log(`\n${results.length - failed.length} passed, ${failed.length} failed, ${results.filter((r) => r.status === 'EXPECTED-FAIL').length} expected failure (P0: ${p0Tail})`);
  process.exit(failed.length ? 1 : 0);
})();
