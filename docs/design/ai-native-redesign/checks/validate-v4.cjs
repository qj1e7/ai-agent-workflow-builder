/* The judge's own checks on version 4. Independent of the builders' gates.
   Run from the repository root:
     node docs/design/ai-native-redesign/checks/validate-v4.cjs [prototype.html] [--only=name,name]
   Prints one line per named check and exits non-zero on any failure. One control is seeded to fail, to prove the
   checks can fail; it is reported as an expected failure and does not count. */
const path = require('path');
const fs = require('fs');
const { repo, chromium, openPage, makeKit } = require('./run.cjs');
const paths = require('./paths-v4.cjs');

const here = path.join(repo, 'docs', 'design', 'ai-native-redesign');
const protoArg = process.argv.slice(2).find((a) => !a.startsWith('--'));
const proto = path.resolve(protoArg || path.join(here, 'prototype.html'));
const url = `file://${proto}`;
const onlyArg = process.argv.find((a) => a.startsWith('--only='));
const only = onlyArg ? onlyArg.slice(7).split(',') : null;
const WEEKLY_SUMMARY = 'every Friday, sum up the tickets we closed this week';
const EMAIL = 'email me a list of open bugs every Monday';
const LONG_DASH = /[\u2013\u2014]/;

const results = [];
const consoleErrors = [];
const fail = (msg) => { throw new Error(msg); };
const ok = (cond, msg) => { if (!cond) fail(msg); };

async function session(browser, body, { width = 1280 } = {}) {
  const o = await openPage(browser, url, { width, height: width > 900 ? 1000 : 844, reduced: true, block: true });
  const k = makeKit(o.page, width, paths);
  k.ctl = (act, arg) => paths.ctl(k, act, arg);
  k.click = async (sel) => { await o.page.locator(sel).first().click(); await k.settle(); };
  k.main = () => o.page.innerText('main');
  k.newChat = async () => { if (await o.page.$('[data-act="newChat"]')) await k.click('[data-act="newChat"]'); };
  try { await body(k, o.page); } finally {
    o.errors.forEach((e) => consoleErrors.push(e));
    await o.context.close();
  }
}

async function check(browser, name, fn, { expectedFail = false } = {}) {
  if (only && !only.includes(name)) return;
  let err = null;
  try { await fn(browser); } catch (e) { err = e; }
  const passed = !err;
  const status = expectedFail ? (passed ? 'FAIL' : 'EXPECTED-FAIL') : passed ? 'PASS' : 'FAIL';
  results.push({ name, status, detail: err ? String(err.message || err) : '' });
  console.log(`${status.padEnd(13)} ${name}${err ? `: ${String(err.message || err).split('\n').join(' | ')}` : ''}${expectedFail && passed ? ': the seeded control passed, so these checks cannot fail' : ''}`);
}

const num = (s) => { const m = String(s || '').match(/\d+/); return m ? +m[0] : null; };

/* Every place that shows how many things need this person, read from the screen. */
async function needCounts(k, page, { operator }) {
  const out = {};
  const badge = async () => num(await page.locator('.hdr .badge[data-val="needs-n"]').first().innerText().catch(() => ''));
  if (operator) {
    await k.go('workflows');
    out.workflowsHeader = num(await page.locator('main #needs-h .count').innerText().catch(() => '0'));
    out.workflowsItems = (await page.locator('main section[aria-labelledby="needs-h"] .queue > li').count()) + ((await page.locator('main section[aria-labelledby="needs-h"]').count()) ? 1 : 0);
  }
  out.badge = await badge();
  await k.go('home');
  const home = await k.main();
  out.homeHeader = num(await page.locator('main #needs-h .count').innerText().catch(() => '0'));
  const rows = await page.locator('main section[aria-labelledby="needs-h"] li.nrow').count();
  const queue = await page.locator('main section[aria-labelledby="needs-h"] .queue > li').count();
  out.homeRows = rows || (queue + ((await page.locator('main section[aria-labelledby="needs-h"]').count()) ? 1 : 0));
  out.homeSeeAll = num((home.match(/See all (\d+) on Workflows/) || [])[1]);
  out.homeLine = num((home.match(/(\d+) (things need|thing needs|requests? (is|are) waiting)/) || [])[1]);
  if (operator) {
    await k.ask('What needs me?');
    out.plannerSay = num((await page.locator('.thread [data-say]').last().innerText()).match(/^(\d+)/)?.[1]);
    out.plannerRows = await page.locator('.thread li.cmsg:last-child li.nrow').count();
    await k.newChat();
  }
  return out;
}
function agree(label, c) {
  const n = c.homeHeader;
  const bad = [];
  ok(n !== null && n > 0, `${label}: Home shows no Needs you count (${JSON.stringify(c)})`);
  if (c.workflowsHeader !== undefined && c.workflowsHeader !== n) bad.push(`Workflows header ${c.workflowsHeader}`);
  if (c.workflowsItems !== undefined && c.workflowsItems !== n) bad.push(`Workflows lists ${c.workflowsItems} items`);
  if (c.badge !== n) bad.push(`tab badge ${c.badge}`);
  if (c.homeRows !== Math.min(n, c.plannerSay === undefined ? n : 3)) bad.push(`Home rows ${c.homeRows}`);
  if (n > 3 && c.plannerSay !== undefined && c.homeSeeAll !== n) bad.push(`See all ${c.homeSeeAll}`);
  if (n <= 3 && c.homeSeeAll !== null) bad.push(`See all shown with only ${n}`);
  if (c.homeLine !== null && c.homeLine !== n) bad.push(`greeting line says ${c.homeLine}`);
  if (c.plannerSay !== undefined && c.plannerSay !== n) bad.push(`Planner says ${c.plannerSay}`);
  if (c.plannerRows !== undefined && c.plannerRows !== n) bad.push(`Planner lists ${c.plannerRows} rows`);
  ok(!bad.length, `${label}: Home says ${n}, but ${bad.join(', ')}`);
  return `${label} ${n}`;
}

/* Visible text of the product (main, dialogs, drawer, menus), without the person's own words or the test controls. */
const SWEEP = {
  updated: /last updated|no update for|update date|who owns (a|the|each) ticket|ticket’s (owner|type)/i,
  teamsPost: /\bpost(s|ed|ing)?\b[^.]{0,30}\bTeams\b|\bTeams (message|post)|\bmessages? (in|to) Teams|\bnudge/i,
  confluence: /Confluence/i,
  ghIssues: /GitHub issues?|bug reports?/i,
  access: /Entra|GitLab|admin tools|who has access|access review/i,
  registries: /Maven|PyPI|\bnpm\b|NuGet|Docker Hub|package registr|security advisor|vulnerab|\bCVE|NVD|CISA|actively exploited|endoflife|support end/i,
  jiraComp: /\bcomponents?\b/i,
  email: /\bsends? (an? )?e-?mails?\b|\be-?mail (me|them|it|a|the)\b|\bSlack\b|Outlook/i,
  tickets: /\b(close|edit|move|delete)s? (the |a |these |those )?(Jira )?tickets?\b/i,
  namedApprovers: /\bbackup\b|asked first|named Approvers?|stop time/i,
  toolDraft: /draft(s|ing)? (a |the |new )?tool|published API/i,
};
async function sweep(page, { preview = false } = {}) {
  return page.evaluate(([src, preview]) => {
    const res = Object.fromEntries(Object.entries(src).map(([k, [s, f]]) => [k, new RegExp(s, f)]));
    const roots = [...document.querySelectorAll('main, .dialog, .drawer, .menu')];
    const h1 = document.querySelector('main h1');
    const pageTagged = !!(h1 && h1.parentElement && h1.parentElement.querySelector('.tag.planned'));
    const UNIT = 'li, tr, article, section, details, .pcard, .card, figure, dd';
    const allowedBlock = (el, re) => {
      if (preview) {
        if (pageTagged && el.closest('main')) return 'planned page';
        for (let u = el.closest(UNIT); u && u.closest('main, .drawer, .dialog'); u = u.parentElement && u.parentElement.closest(UNIT)) {
          if (u.querySelector('.tag.planned')) return 'planned unit';
          if (u.tagName === 'SECTION') break;
        }
      }
      if (el.closest('.cmsg.me, .testctl, .abil-not, .cap-not, [data-pres^="cant:"], [data-pres^="part:"], [data-pres^="refuse:"], [data-pres^="down:"]')) return 'not-yet or can’t';
      const msg = el.closest('li.cmsg');
      if (msg && msg.querySelector('[data-pres^="cant:"], [data-pres^="part:"], [data-pres^="refuse:"], [data-pres^="down:"]')) return 'can’t answer';
      for (let b = el; b && !roots.includes(b); b = b.parentElement) {
        if (b.querySelector && b.querySelector('.tag.planned')) return 'planned tag';
        if (/^(LI|TR|P|ARTICLE|FIGURE|DD|SECTION)$/.test(b.tagName) || b.classList.contains('alt')) {
          if ([...b.querySelectorAll('.cap-note, small, .small')].some((x) => /^\s*Planned\s*$/.test(x.textContent))) return 'planned note';
          if ([...b.querySelectorAll('*')].some((x) => !x.children.length && /^\s*Planned\s*$/i.test(x.textContent))) return 'planned mark';
          const NEG = /can’t|cannot|isn’t (built|connected|here)|not built|Not yet|on the team’s plan|so far|ask the team to add/i;
          if ([...b.querySelectorAll('h2, h3, h4, legend')].some((h) => NEG.test(h.textContent))) return 'negated heading';
          const said = b.innerText.split(/(?<=[.?!])\s+|\n+/).filter((x) => re.test(x));
          if (said.length && said.every((x) => NEG.test(x))) return 'negated sentence';
          break;
        }
      }
      return null;
    };
    const hits = [];
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const el = n.parentElement;
        if (!el || !el.getClientRects().length || el.closest('.vh')) continue;
        const text = n.textContent;
        for (const [cap, re] of Object.entries(res)) {
          if (!re.test(text)) continue;
          if (allowedBlock(el, re)) continue;
          hits.push({ cap, text: text.trim().slice(0, 140), where: `${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]}` });
        }
      }
    }
    return hits;
  }, [Object.fromEntries(Object.entries(SWEEP).map(([k, r]) => [k, [r.source, r.flags]])), preview]);
}

/* Tab from the top until the target has focus, then say whether the focus can be seen. Same rule as quality.cjs. */
async function tabReach(page, sel, { fromTop = true, max = 70 } = {}) {
  if (fromTop) await page.evaluate(() => { const p = document.createElement('span'); p.tabIndex = -1; document.body.prepend(p); p.focus(); p.remove(); });
  for (let i = 1; i <= max; i += 1) {
    await page.keyboard.press('Tab');
    const r = await page.evaluate((s) => {
      const el = document.activeElement;
      if (!el || !el.matches(s)) return null;
      const cs = getComputedStyle(el);
      let ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');
      if (!ring) {
        const chain = [el];
        while (chain.length < 4 && chain[chain.length - 1].parentElement) chain.push(chain[chain.length - 1].parentElement);
        const sig = () => chain.map((n) => { const c = getComputedStyle(n); return `${c.outlineStyle}${c.outlineWidth}${c.boxShadow}${c.borderColor}`; }).join('|');
        const on = sig(); el.blur(); const off = sig(); el.focus();
        ring = on !== off;
      }
      return { ring };
    }, sel);
    if (r) return { presses: i, ring: r.ring };
  }
  return { presses: null, ring: false };
}

async function main() {
  const browser = await chromium.launch();
  const B = browser;

  await check(B, 'counts-agree', async (b) => {
    const seen = [];
    await session(b, async (k, page) => { seen.push(agree('normal week', await needCounts(k, page, { operator: true }))); });
    await session(b, async (k, page) => {
      await k.go('workflows'); await k.click('main [data-act="run"][data-arg="sw"]'); await k.click('[data-act="approve"][data-arg="sw"]');
      await k.waitText(/approved, and the platform created the tickets/);
      seen.push(agree('after approving the upgrade tickets', await needCounts(k, page, { operator: true })));
    });
    await session(b, async (k, page) => {
      await k.go('workflows'); await k.click('main [data-act="retryIssues"]'); await k.waitText(/Done, nothing new today/);
      seen.push(agree('after retrying the stopped run', await needCounts(k, page, { operator: true })));
    });
    await session(b, async (k, page) => { await k.setUser('bob'); seen.push(agree('Bob', await needCounts(k, page, { operator: false }))); });
    await session(b, async (k, page) => { await k.ctl('Jira stops answering'); seen.push(agree('Jira down', await needCounts(k, page, { operator: true }))); });
    await session(b, async (k, page) => {
      const tab = num(await page.locator('.tabbar .badge').first().innerText().catch(() => ''));
      const head = num(await page.locator('main #needs-h .count').innerText().catch(() => ''));
      ok(tab === head, `phone tab bar badge ${tab}, Home says ${head}`);
      seen.push(`phone ${tab}`);
    }, { width: 390 });
    console.log(`              ${seen.join('; ')}`);
  });

  await check(B, 'card-agrees', async (b) => session(b, async (k, page) => {
    await k.ask(WEEKLY_SUMMARY);
    const read = async (label) => {
      const foot = await page.locator('.pcard .pcard-f').innerText();
      const disabled = await page.locator('.pcard [data-act="turnOn"]').isDisabled();
      const m = foot.match(/(\d+) choices? left: ([^.]+)\./);
      const n = m ? +m[1] : /Nothing is unclear/.test(foot) ? 0 : null;
      ok(n !== null, `${label}: footer has no count: ${foot}`);
      ok(disabled === n > 0, `${label}: footer says ${n} left but Turn it on is ${disabled ? 'disabled' : 'enabled'}`);
      if (m) ok(m[2].split(/, | and /).length === n, `${label}: footer count ${n} names ${m[2]}`);
      const missing = await page.locator('.pcard .schip.missing').count();
      ok(missing === n, `${label}: footer says ${n} left, the card marks ${missing} parts as please choose`);
      const all = await k.main();
      const other = [...all.matchAll(/(\d+) (more )?(choices?|answers?|questions?) (left|to go)|I need (\d+)/g)].map((x) => +(x[1] || x[5]));
      ok(other.every((v) => v === n), `${label}: the page names ${other.join(', ')} while the footer says ${n}`);
      const say = await page.locator('.thread [data-say]').last().innerText();
      ok(!/\d+ (more )?(choices?|answers?)/.test(say), `${label}: the chat sentence repeats a count: ${say}`);
      return `${label} ${n}`;
    };
    const log = [await read('start')];
    await page.selectOption('#fix-tickets', 'created'); await k.settle(); log.push(await read('tickets'));
    await page.selectOption('#fix-action', 'list'); await k.settle(); log.push(await read('action'));
    await page.selectOption('#fix-project', 'MOCK'); await k.settle(); log.push(await read('project'));
    await page.fill('#sched-time', '17:00'); await k.settle(); log.push(await read('time'));
    await page.selectOption('#sched-freq', 'day'); await k.settle(); log.push(await read('how often'));
    await page.selectOption('#fix-tickets', 'old'); await k.settle(); log.push(await read('tickets again'));
    await page.selectOption('#fix-project', 'OPS'); await k.settle(); log.push(await read('project again'));
    console.log(`              ${log.join('; ')}`);
  }));

  await check(B, 'roles-bob-creates-nothing', async (b) => {
    for (const preview of [false, true]) {
      await session(b, async (k, page) => {
        await k.setUser('bob');
        if (preview) await k.ctl('preview', 'on');
        const creation = 'main :is([data-ask], form[data-submit="ask"], [data-act="example"], [data-act="say"], [data-act="askPlanner"], [data-act="newChat"], [data-act="n8nNew"], #sw-name, form[data-submit="swFind"], form[data-submit="swAdd"])';
        const named = /^(Set up|Ask the Planner|Start in n8n|Add software|Find it|New chat|Turn it on)/;
        const at = async (where) => {
          ok((await page.locator(creation).count()) === 0, `${where}${preview ? ' (Planned shown)' : ''}: Bob sees a creation control`);
          const labels = await page.$$eval('main button', (bs) => bs.filter((x) => x.getClientRects().length).map((x) => x.innerText.trim()));
          const hit = labels.find((l) => named.test(l));
          ok(!hit, `${where}${preview ? ' (Planned shown)' : ''}: Bob sees “${hit}”`);
        };
        await at('Home');
        await k.go('workflows'); await at('Workflows');
        await k.go('software'); await at('Software watchlist');
        ok((await page.locator('.hdr [data-act="go"][data-arg="agents"]').count()) === 0, 'Bob has an Agent library link');
      });
    }
    await session(b, async (k, page) => {
      await k.setUser('bob');
      ok((await page.locator('.tabbar [data-act="go"][data-arg="agents"]').count()) === 0, 'Bob has an Agents tab on a phone');
    }, { width: 390 });
  });

  await check(B, 'roles-alice-not-own-test-run', async (b) => session(b, async (k, page) => {
    await k.ask(WEEKLY_SUMMARY);
    await page.selectOption('#fix-project', 'MOCK'); await k.settle();
    await page.fill('#sched-time', '17:00'); await k.settle();
    await k.click('[data-act="turnOn"]');
    await k.click('[data-act="testRun"]');
    await k.waitText(/another Approver must decide/);
    ok((await page.locator('[data-act="approve"], [data-act="decline"]').count()) === 0, 'Alice has Approve or Decline on her own test run');
    await k.go('workflows');
    ok(!/Review and decide/.test(await page.locator('main .wf-row:has-text("Friday closed ticket summary")').innerText()), 'Workflows offers Alice a decision on her own run');
    ok((await page.locator('main [data-act="run"][data-arg="conf"]:has-text("Review and decide")').count()) === 0, 'Needs you offers Alice her own run');
    await k.go('home');
    ok(!/test run by Alice/.test(await k.main()), 'Home lists Alice’s own test run as needing her');
    await k.click('.hdr [data-act="teams"]');
    const drawer = await page.innerText('.drawer');
    const card = drawer.split(/AI Workflow Builder ·/).find((x) => /Friday closed ticket summary/.test(x)) || '';
    ok(card && !/Who can decide\s*[^\n]*Alice/.test(card), `the Teams card lists Alice as able to decide on her own run: ${card.slice(0, 200)}`);
  }));

  await check(B, 'roles-access-review-two-approvers', async (b) => session(b, async (k, page) => {
    await k.go('workflows');
    ok((await page.locator('main [data-act="workflow"][data-arg="access"]').count()) === 0, 'the access review shows with Planned features hidden');
    await k.ctl('preview', 'on');
    await k.go('workflows'); await k.click('main [data-act="workflow"][data-arg="access"]');
    const text = await k.main();
    ok(/First Bob, with Siti as backup\. Then Alice, with Arun as backup\./.test(text), 'the access review does not name two Approvers in turn');
    ok(/approved by Bob, then Alice/.test(text), 'its last run does not show two yeses in turn');
    ok((await page.locator('main .tag.planned').count()) >= 1, 'the access review is not tagged Planned');
  }));

  await check(B, 'teams-drawer-never-approves', async (b) => {
    const looks = async (k, page, label) => {
      await k.click('.hdr [data-act="teams"]');
      const n = await page.locator('.drawer :is([data-act="approve"], [data-act="decline"], button:text-matches("^(Approve|Decline|Yes|No|Say yes)", "i"))').count();
      ok(n === 0, `${label}: the Teams drawer has ${n} decision buttons`);
      await page.keyboard.press('Escape'); await k.settle();
      return label;
    };
    const seen = [];
    await session(b, async (k, page) => { seen.push(await looks(k, page, 'Alice')); });
    await session(b, async (k, page) => { await k.setUser('bob'); seen.push(await looks(k, page, 'Bob')); });
    await session(b, async (k, page) => { await k.ctl('preview', 'on'); seen.push(await looks(k, page, 'Planned shown')); });
    await session(b, async (k, page) => {
      await k.ask(WEEKLY_SUMMARY); await page.selectOption('#fix-project', 'MOCK'); await k.settle(); await page.fill('#sched-time', '17:00'); await k.settle();
      await k.click('[data-act="turnOn"]'); await k.click('[data-act="testRun"]'); await k.waitText(/another Approver must decide/);
      await k.setUser('bob'); seen.push(await looks(k, page, 'Bob with a test run waiting'));
    });
    console.log(`              ${seen.join('; ')}`);
  });

  await check(B, 'safety-words', async (b) => {
    const hits = [];
    const look = async (page, screen) => { (await sweep(page)).forEach((h) => hits.push({ screen, ...h })); };
    const states = [
      ['home', async () => {}],
      ['day one', async (k) => k.setDay('one')],
      ['offline', async (k) => k.ctl('modelOn', 'off')],
      ['workflows', async (k) => k.go('workflows')],
      ...['issues', 'nudge'].map((id) => [`workflow ${id}`, async (k, page) => { await k.go('workflows'); await k.click(`main [data-act="workflow"][data-arg="${id}"]`); await page.$$eval('main details', (ds) => ds.forEach((d) => { d.open = true; })); await k.click('main [data-act="menu"]'); }]),
      ...['issues', 'nudge'].map((id) => [`run ${id}`, async (k) => { await k.go('workflows'); await k.click(`main [data-act="workflow"][data-arg="${id}"]`); await k.click('main [data-act="watch"]'); await k.click('main [data-act="runDetail"]'); }]),
      ['run sw', async (k) => { await k.go('workflows'); await k.click('main [data-act="run"][data-arg="sw"]'); await k.click('main [data-act="runDetail"]'); }],
      ['software', async (k, page) => { await k.go('software'); for (const key of ['lj', 'fa', 'ls']) { await page.click(`main [data-act="swHist"][data-arg="${key}"]`); await k.settle(150); } }],
      ['library what it can do', async (k) => k.go('agents')],
      ['library agents', async (k) => { await k.go('agents'); await k.click('[data-act="libTab"][data-arg="agents"]'); }],
      ['library tools', async (k) => { await k.go('agents'); await k.click('[data-act="libTab"][data-arg="tools"]'); }],
      ...['lead', 'trouble', 'checker', 'writer', 'jira', 'summary'].map((id) => [`agent ${id}`, async (k, page) => { await k.go('agents'); await k.click('[data-act="libTab"][data-arg="agents"]'); await k.click(`main [data-act="agent"][data-arg="${id}"]`); await page.$$eval('.dialog details', (ds) => ds.forEach((d) => { d.open = true; })); }]),
      ...['connections', 'people', 'model', 'usage'].map((tab) => [`settings ${tab}`, async (k) => { await k.click('.hdr [data-act="go"][data-arg="settings"]'); await k.click(`[data-act="setTab"][data-arg="${tab}"]`); }]),
      ['teams', async (k) => k.click('.hdr [data-act="teams"]')],
      ['planner check', async (k) => k.click('main [data-act="example"][data-arg="0"]').then(() => k.replied())],
      ['planner why', async (k) => k.click('main [data-act="example"][data-arg="1"]').then(() => k.replied())],
      ['planner set up another', async (k) => k.click('main [data-act="example"][data-arg="2"]').then(() => k.replied())],
      ['planner needs', async (k) => k.ask('What needs me?')],
      ['planner card', async (k, page) => { await k.ask(WEEKLY_SUMMARY); await page.$$eval('main details', (ds) => ds.forEach((d) => { d.open = true; })); }],
      ['planner watch', async (k) => k.ask('Monitor Kubernetes releases')],
      ['planner email', async (k) => k.ask(EMAIL)],
      ['planner abilities', async (k) => k.ask('What can you do?')],
      ['planner access', async (k) => k.ask('Every quarter, check who has access to GitLab')],
      ['planner confluence', async (k) => k.ask('Every Friday, update the Confluence page with the closed tickets')],
      ['planner component', async (k) => k.ask('Put new tickets in the Platform component')],
      ['planner teams post', async (k) => k.ask('Every Monday, post the open tickets in Teams')],
      ['planner close', async (k) => k.ask('Close the tickets that are done every Friday')],
      ['bob home', async (k) => k.setUser('bob')],
      ['bob run', async (k) => { await k.setUser('bob'); await k.click('main [data-act="run"][data-arg="sw"]'); }],
      ['bob workflows', async (k) => { await k.setUser('bob'); await k.go('workflows'); }],
    ];
    for (const [screen, prep] of states) {
      await session(b, async (k, page) => { await prep(k, page); await k.settle(400); await look(page, screen); });
    }
    if (hits.length) fail(`${hits.length} unallowed: ${hits.map((h) => `[${h.screen}] ${h.cap} in ${h.where}: “${h.text}”`).join(' || ')}`);
  });

  await check(B, 'preview-tags-planned', async (b) => {
    const hits = [];
    const states = [
      ['home', async () => {}],
      ['workflows', async (k) => k.go('workflows')],
      ...['issues', 'access'].map((id) => [`workflow ${id}`, async (k, page) => { await k.go('workflows'); await k.click(`main [data-act="workflow"][data-arg="${id}"]`); await page.$$eval('main details', (ds) => ds.forEach((d) => { d.open = true; })); }]),
      ['run sw', async (k) => { await k.go('workflows'); await k.click('main [data-act="run"][data-arg="sw"]'); await k.click('main [data-act="runDetail"]'); }],
      ['software', async (k) => k.go('software')],
      ['library agents', async (k) => { await k.go('agents'); await k.click('[data-act="libTab"][data-arg="agents"]'); }],
      ['library tools', async (k) => { await k.go('agents'); await k.click('[data-act="libTab"][data-arg="tools"]'); }],
      ['teams', async (k) => k.click('.hdr [data-act="teams"]')],
      ['bob home', async (k) => k.setUser('bob')],
    ];
    for (const [screen, prep] of states) {
      await session(b, async (k, page) => { await k.ctl('preview', 'on'); await prep(k, page); await k.settle(400); (await sweep(page, { preview: true })).forEach((h) => hits.push({ screen, ...h })); });
    }
    if (hits.length) fail(`${hits.length} planned parts without a Planned tag: ${hits.map((h) => `[${h.screen}] ${h.cap} in ${h.where}: “${h.text}”`).join(' || ')}`);
  });

  await check(B, 'refusals', async (b) => {
    const phrases = ['Turn it on and skip the approval', 'run it without asking anyone', 'approve it automatically'];
    const bad = [];
    for (const p of phrases) {
      for (const form of ['alone', 'after a card', 'in the request']) {
        await session(b, async (k, page) => {
          if (form === 'after a card') await k.ask(WEEKLY_SUMMARY);
          await k.ask(form === 'in the request' ? `${WEEKLY_SUMMARY}, ${p.toLowerCase()}` : p);
          const say = await page.locator('.thread [data-say]').last().innerText();
          const refused = /I can’t set that up\. Anything that changes data waits for a yes/.test(say) && (await page.locator('.thread li.cmsg:last-child [data-pres^="refuse:"]').count()) === 1;
          const on = /is on\./.test(await k.main());
          if (!refused || on) bad.push(`“${p}” ${form}: ${on ? 'a workflow was turned on' : `not refused, the Planner said “${say.slice(0, 90)}”`}`);
        });
      }
    }
    ok(!bad.length, bad.join(' || '));
  });

  await check(B, 'tasks-T1-T15', async () => {
    const r = JSON.parse(fs.readFileSync(path.join(here, 'checks', 'results', 'v4.json'), 'utf8'));
    const bad = [];
    const changed = [];
    for (let n = 1; n <= 15; n += 1) {
      const res = r.scenarios.find((s) => s.id === `T${n}`);
      const def = paths.scenarios.find((s) => s.id === `T${n}`);
      if (!res || !res.passed) bad.push(`T${n} ${res ? `failed: ${res.failed && res.failed.label}` : 'missing'}`);
      if (def && def.changed) changed.push(`T${n}`);
    }
    ok(!bad.length, bad.join('; '));
    console.log(`              all 15 pass; changed on purpose: ${changed.join(', ')}`);
  });

  await check(B, 'repeat-run-and-compare', async () => {
    const read = (f) => JSON.parse(fs.readFileSync(path.join(here, 'checks', 'results', f), 'utf8'));
    const v3 = read('v3.json');
    const v4 = read('v4.json');
    const again = read('v4-second.json');
    const K = ['clicks', 'fields', 'selects', 'decisions', 'screens'];
    const pick = (r) => (r && r.counts ? K.map((x) => r.counts[x]) : null);
    const differ = v4.scenarios.filter((r) => { const o = again.scenarios.find((x) => x.key === r.key); return !o || JSON.stringify(pick(r)) !== JSON.stringify(pick(o)) || r.passed !== o.passed; }).map((r) => r.key);
    const fmt = (c) => (c ? c.join(' / ') : '-');
    const sum3 = (c) => c[0] + c[1] + c[2];
    const rows = v4.scenarios.map((r) => {
      const old = v3.scenarios.find((x) => x.key === r.key);
      const def = paths.scenarios.find((x) => x.id === r.id && x.viewport === r.viewport);
      const a = old && !old.notPossible ? pick(old) : null;
      const b = pick(r);
      const d = a && b ? sum3(b) - sum3(a) : null;
      return `| ${r.id} | ${r.viewport} | ${old ? (old.notPossible ? 'not possible' : fmt(a)) : 'new'} | ${fmt(b)} | ${d === null ? '' : d > 0 ? `+${d}` : d} | ${r.passed ? 'yes' : 'NO'} | ${(def && def.changed) || ''} | ${r.steps.map((x) => `${x.label}${x.decision ? ' (decision)' : ''}`).join('; ')} |`;
    });
    fs.writeFileSync(path.join(here, 'checks', 'results', 'v4-compare.md'), [
      '# Version 3 against version 4', '',
      'Counts are clicks / fields / selects / decisions / screens, from `v3.json` and `v4.json`. The change is in interactions: clicks plus fields plus selects. A decision is also a click, a field or a select. Test controls are never counted. Written by `validate-v4.cjs`.', '',
      `Repeat run (\`v4-second.json\`): ${differ.length ? `differs in ${differ.join(', ')}` : `identical counts and results for all ${v4.scenarios.length} scenarios`}.`, '',
      '| Id | Width | v3 | v4 | Change | v4 passed | Changed on purpose | v4 steps |', '|---|---|---|---|---|---|---|---|', ...rows, ''].join('\n'));
    ok(!differ.length, `the two v4 runs differ in ${differ.join(', ')}`);
    console.log(`              ${v4.scenarios.length} scenarios identical across two runs; wrote results/v4-compare.md`);
  });

  await check(B, 'no-long-dashes', async () => {
    const files = [proto, ...['AI-NATIVE-UX-REDESIGN.md', 'UX-AUDIT.md', 'IMPLEMENTATION-PLAN.md', 'USER-JOURNEY-COMPARISON.md', 'checks/README.md', 'screenshots/README.md', 'checks/paths-v4.cjs', 'checks/validate-v4.cjs'].map((f) => path.join(here, f))];
    const bad = [];
    const missing = [];
    for (const f of files) {
      if (!fs.existsSync(f)) { missing.push(path.relative(here, f)); continue; }
      fs.readFileSync(f, 'utf8').split('\n').forEach((line, i) => { if (LONG_DASH.test(line)) bad.push(`${path.relative(here, f)}:${i + 1}`); });
    }
    ok(!bad.length, `long dashes at ${bad.slice(0, 10).join(', ')}`);
    console.log(`              checked ${files.length - missing.length} files${missing.length ? `; not there to check: ${missing.join(', ')}` : ''}`);
  });

  await check(B, 'down-state-honest', async (b) => session(b, async (k, page) => {
    await k.ctl('Jira stops answering');
    await k.go('workflows');
    const text = await k.main();
    ok(/Jira isn’t answering/.test(text), 'Workflows does not say Jira is down');
    ok(!/it’s working again now/.test(text), 'with Jira down, the AI troubleshooter on Workflows says Jira is “working again now” and calls a retry safe');
    await k.click('main [data-act="retryIssues"]');
    await page.waitForTimeout(4000);
    ok(!/The retry read Jira/.test(await k.main()), 'with Jira down, Retry the run reports that it read Jira');
  }));

  await check(B, 'one-version-per-fact', async (b) => session(b, async (k, page) => {
    const seen = {};
    await k.go('software');
    seen.watchlistRow = ((await page.locator('main tr:has-text("FastAPI")').first().innerText()).match(/0\.1\d\d\.\d+/g) || []).pop();
    await page.click('main [data-act="swHist"][data-arg="fa"]'); await k.settle();
    seen.watchlistHistory = ((await k.main()).match(/Found (0\.120\.\d)/) || [])[1];
    await k.click('main [data-act="run"][data-arg="sw"]');
    seen.approvalPanel = ((await k.main()).match(/Upgrade FastAPI from 0\.118\.0 to (0\.120\.\d)/) || [])[1];
    await k.click('.hdr [data-act="teams"]');
    seen.teamsCard = ((await page.innerText('.drawer')).match(/Upgrade FastAPI to (0\.120\.\d)/) || [])[1];
    const vals = new Set(Object.values(seen));
    ok(vals.size === 1, `FastAPI’s newest version differs by screen: ${JSON.stringify(seen)}`);
  }));

  await check(B, 'keyboard-primary-actions', async (b) => {
    const rows = [];
    const reach = async (label, prep, sel, opts) => session(b, async (k, page) => {
      await prep(k, page);
      const r = await tabReach(page, sel, opts);
      rows.push(`${label} ${r.presses === null ? 'NOT REACHED' : `${r.presses}${r.ring ? '' : ' NO RING'}`}`);
    });
    const card = async (k, page) => { await k.ask(WEEKLY_SUMMARY); await page.selectOption('#fix-project', 'MOCK'); await k.settle(); await page.fill('#sched-time', '17:00'); await k.settle(); };
    await reach('A Turn it on', async (k, page) => { await k.setDay('one'); await card(k, page); }, '[data-act="turnOn"]');
    await reach('B Retry the run', async (k) => k.go('workflows'), 'main [data-act="retryIssues"]');
    await reach('B-home Retry the run', async () => {}, 'main [data-act="retryIssues"]');
    await reach('C Review and decide', async (k) => k.setUser('bob'), '[data-act="run"][data-arg="sw"]');
    await reach('C Approve', async (k) => { await k.setUser('bob'); await k.click('main [data-act="run"][data-arg="sw"]'); }, '[data-act="approve"][data-arg="sw"]');
    await reach('C-self Do a test run', async (k, page) => { await card(k, page); await k.click('[data-act="turnOn"]'); }, '[data-act="testRun"]');
    await reach('D Set that up', async (k) => k.ask(EMAIL), '[data-act="instead"]');
    await reach('E Jira project', async (k) => k.ask('Every Friday at 17:00, sum up the tickets we closed this week in project MOCK'), '#fix-project');
    await reach('F Report to support', async (k) => k.go('workflows'), 'main [data-act="report"]');
    await reach('F Send report', async (k) => { await k.go('workflows'); await k.click('main [data-act="report"]'); }, '[data-act="sendReport"]', { fromTop: false });
    await reach('G Add Kubernetes', async (k) => { await k.ask('Monitor Kubernetes releases'); await k.click('[data-act="repoOk"]'); await k.click('[data-act="verNewest"]'); }, '[data-act="watchAdd"]');
    await reach('H More actions', async (k) => { await k.go('workflows'); await k.click('main [data-act="workflow"][data-arg="issues"]'); }, 'main [data-act="menu"]');
    await reach('H Delete workflow', async (k) => { await k.go('workflows'); await k.click('main [data-act="workflow"][data-arg="nudge"]'); await k.click('main [data-act="menu"]'); await k.click('[data-act="menuPick"][data-arg="askDelete:nudge"]'); }, '[data-act="confirmDelete"]', { fromTop: false });
    console.log(`              Tab presses: ${rows.join('; ')}`);
    ok(!rows.some((r) => /NOT REACHED|NO RING/.test(r)), rows.filter((r) => /NOT REACHED|NO RING/.test(r)).join('; '));
  });

  await check(B, 'menu-keys', async (b) => session(b, async (k, page) => {
    await k.go('workflows'); await k.click('main [data-act="workflow"][data-arg="issues"]');
    await page.focus('main [data-act="menu"]');
    await page.keyboard.press('Enter'); await k.settle();
    const at = () => page.evaluate(() => document.activeElement.textContent.trim());
    ok((await page.locator('main [data-act="menu"]').getAttribute('aria-expanded')) === 'true', 'More actions does not say it is expanded');
    const first = await at();
    await page.keyboard.press('ArrowDown'); const second = await at();
    await page.keyboard.press('End'); const last = await at();
    await page.keyboard.press('Home'); const home = await at();
    ok(first === 'Run now' && second !== first && last === 'Delete' && home === 'Run now', `arrows move through the menu: ${[first, second, last, home].join(' > ')}`);
    await page.keyboard.press('Escape'); await k.settle();
    ok((await page.locator('.menu').count()) === 0, 'Escape does not close the menu');
    ok(await page.evaluate(() => document.activeElement.matches('[data-act="menu"]')), 'focus does not return to More actions');
  }));

  await check(B, 'control-bob-has-a-text-box', async (b) => session(b, async (k, page) => {
    await k.setUser('bob');
    ok((await page.locator('main [data-ask]').count()) === 1, 'seeded control: Bob has the Planner box');
  }), { expectedFail: true });

  await browser.close();
  const real = results.filter((r) => r.status !== 'EXPECTED-FAIL');
  const failed = real.filter((r) => r.status === 'FAIL');
  const errs = [...new Set(consoleErrors)];
  if (errs.length) console.log(`console or page errors during the checks: ${errs.slice(0, 5).join(' | ')}`);
  console.log(`\n${real.length - failed.length} passed, ${failed.length} failed, ${results.length - real.length} expected failure`);
  if (proto === path.join(here, 'prototype.html')) fs.writeFileSync(path.join(here, 'checks', 'results', 'v4-validate.json'), `${JSON.stringify({ prototype: path.relative(repo, proto), results, consoleErrors: errs }, null, 2)}\n`);
  process.exit(failed.length || results.some((r) => r.status === 'FAIL') ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
