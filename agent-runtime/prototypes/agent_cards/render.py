"""PROTOTYPE, throwaway. Turns results.json into one HTML file you can double-click."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cards import CATALOG  # noqa: E402

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent cards prototype</title>
<style>
:root {
  --bg: #f4f5f8; --panel: #ffffff; --text: #18202e; --muted: #5b6475; --line: #dde1e8;
  --accent: #2552c9; --accent-soft: #e8eefc; --good: #1d7a46; --good-soft: #e5f4ec;
  --warn: #9a5b00; --warn-soft: #fdf1dc; --bad: #b42318; --bad-soft: #fdeceb; --chip: #eef0f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #11151c; --panel: #1a2029; --text: #e7eaf0; --muted: #9aa3b2; --line: #2c3440;
    --accent: #7ea2ff; --accent-soft: #1f2b47; --good: #5fd08f; --good-soft: #17301f;
    --warn: #f0b45a; --warn-soft: #33270f; --bad: #ff8a80; --bad-soft: #3a1a18; --chip: #262d38;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding: 32px 16px 64px; }
.pair { display: grid; grid-template-columns: 1fr; gap: 0 28px; }
@media (min-width: 1000px) { .pair { grid-template-columns: 1fr 1fr; } }
.runlabel { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); margin: 14px 0 0; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0 0 6px; }
h3 { font-size: 15px; margin: 18px 0 6px; }
p { margin: 0 0 8px; }
.muted { color: var(--muted); }
.tag { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px;
  background: var(--warn-soft); color: var(--warn); }
.question { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; margin: 16px 0; }
.summary { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 8px; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; min-width: 150px; }
.stat b { display: block; font-size: 20px; }
nav { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin: 24px 0 16px; overflow-x: auto; }
nav button { font: inherit; background: none; border: 0; padding: 10px 14px; color: var(--muted); cursor: pointer;
  border-bottom: 2px solid transparent; white-space: nowrap; }
nav button[aria-selected="true"] { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
section.item { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin: 0 0 16px; }
.typed { border-left: 3px solid var(--accent); padding: 2px 0 2px 12px; margin: 0 0 8px; }
.hoped { font-size: 14px; color: var(--muted); }
.card { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 6px; }
.name { font-size: 18px; font-weight: 700; margin: 10px 0 2px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 13px; background: var(--chip); border-radius: 6px; padding: 2px 8px; }
.tool { font: 12px/1.6 ui-monospace, Menlo, monospace; border-radius: 6px; padding: 1px 6px; background: var(--chip); white-space: nowrap; }
.tool.write { background: var(--accent-soft); color: var(--accent); }
ol.plan { margin: 0; padding-left: 22px; }
ol.plan li { margin: 0 0 6px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.box { border-radius: 8px; padding: 8px 12px; margin: 10px 0 0; font-size: 14px; }
.box.good { background: var(--good-soft); color: var(--good); }
.box.warn { background: var(--warn-soft); color: var(--warn); }
.box.bad { background: var(--bad-soft); color: var(--bad); }
.box ul { margin: 4px 0 0; padding-left: 18px; }
.decision { font-weight: 700; }
.match { font-size: 13px; font-weight: 600; margin-left: 8px; }
.match.yes { color: var(--good); } .match.no { color: var(--bad); }
.foot { font-size: 12px; color: var(--muted); margin-top: 12px; }
.agentstep { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin: 6px 0; }
@media (max-width: 600px) { .stat { min-width: calc(50% - 5px); } }
</style>
</head>
<body>
<main>
  <span class="tag">Throwaway prototype, not the product</span>
  <h1>Agent cards prototype</h1>
  <p class="muted" id="meta"></p>
  <div class="question">
    <p><b>The question:</b> can our AI model turn a plain-English task into a good <b>agent card</b>, and can the
    <b>Room lead</b> pick the right saved agents for a new task?</p>
    <p class="muted">An agent card is data, not code: a name, a purpose, a plan, the tools it may use (only from a fixed
    list), and how many people must approve each write. The platform picks who. The "Checks" under each card are what the platform would refuse or flag
    before anyone could save it.</p>
  </div>
  <div class="summary" id="summary"></div>
  <nav role="tablist" id="tabs"></nav>
  <div id="panel"></div>
</main>
<script>
const DATA = __DATA__;
const CATALOG = __CATALOG__;
const DECISIONS = { use_one: "Use one saved agent", use_several: "Bring in several agents",
  new_agent: "Draft a new agent", cannot_do: "Can't do this" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const toolChip = (t) => {
  const kind = (CATALOG[t] || ["unknown"])[0];
  return `<span class="tool ${kind}" title="${esc((CATALOG[t] || ["", "Not in the tool list"])[1])}">${esc(t)}</span>`;
};
const foot = (r) => r.seconds ? `<p class="foot">${r.seconds} s, ${r.tokens?.[0] ?? "?"} tokens in, ${r.tokens?.[1] ?? "?"} out</p>` : "";
const checks = (list, okText) => !list ? "" : list.length
  ? `<div class="box warn"><b>Checks flagged ${list.length}:</b><ul>${list.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>`
  : `<div class="box good">${okText}</div>`;

function card(r) {
  if (r.error) return `<div class="box bad"><b>The model call failed:</b> ${esc(r.error)}</div>`;
  const c = r.answer;
  if (!c.can_do) return `<div class="card"><p class="name">${esc(c.name)}</p>
    <div class="box bad"><b>Says it can't do this:</b> ${esc(c.why_not || c.purpose)}</div>
    ${list("What it would need", (c.missing_tools || []).map((m) => `${esc(m.need)}: ${esc(m.why)}`))}${foot(r)}</div>`;
  const approvals = Object.fromEntries((c.approvals || []).map((a) => [a.tool, a]));
  const steps = (c.steps || []).map((s) => {
    const a = s.tool && approvals[s.tool];
    return `<li>${esc(s.say)} ${s.tool ? toolChip(s.tool) : ""}${a ? ` <span class="muted">(${a.approvers} approver${a.approvers > 1 ? "s, one after the other" : ""})</span>` : ""}</li>`;
  }).join("");
  const inputs = (c.inputs || []).length ? `<h3>What the operator gives each run</h3><table><tr><th>Input</th><th>What</th><th>Example</th></tr>${
    c.inputs.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.what)}</td><td>${esc(i.example)}</td></tr>`).join("")}</table>` : "";
  return `<div class="card">
    <p class="name">${esc(c.name)}</p><p>${esc(c.purpose)}</p>
    <div class="chips">${(c.good_for || []).map((g) => `<span class="chip">"${esc(g)}"</span>`).join("")}</div>
    <h3>Plan</h3><ol class="plan">${steps}</ol>
    ${list("Approvals (the platform picks who, never the person who started the run)", (c.approvals || []).map((a) => `${toolChip(a.tool)} ${a.approvers} approver${a.approvers > 1 ? "s" : ""}. ${esc(a.why)}`), true)}
    ${inputs}
    ${list("Tools it said are missing", (c.missing_tools || []).map((m) => `<b>${esc(m.need)}</b>: ${esc(m.why)}`), true)}
    ${list("What it would ask before saving", (c.questions || []).map(esc), true)}
    ${checks(r.checks, "Passes the platform's checks: only real tools, and every write has an approval.")}
    ${foot(r)}</div>`;
}
function list(title, items, raw) {
  return items.length ? `<h3>${title}</h3><ul>${items.map((i) => `<li>${raw ? i : esc(i)}</li>`).join("")}</ul>` : "";
}
function choice(r, hoped) {
  if (r.error) return `<div class="box bad"><b>The model call failed:</b> ${esc(r.error)}</div>`;
  const c = r.answer;
  const match = hoped ? (c.decision === hoped ? `<span class="match yes">As hoped</span>` : `<span class="match no">Not as hoped</span>`) : "";
  const agents = (c.agents || []).map((a, i) => `<div class="agentstep"><b>${i + 1}. ${esc(a.agent)}</b>: ${esc(a.part)}
    ${Object.keys(a.inputs || {}).length ? `<div class="chips" style="margin-top:6px">${Object.entries(a.inputs).map(([k, v]) => `<span class="chip">${esc(k)} = ${esc(v)}</span>`).join("")}</div>` : ""}</div>`).join("");
  return `<div class="card"><p><span class="decision">${esc(DECISIONS[c.decision] || c.decision)}</span>${match}</p>
    ${agents}${c.new_agent ? `<p><b>New agent:</b> ${esc(c.new_agent)}</p>` : ""}
    <p><b>Why:</b> ${esc(c.reason)}</p>
    ${list("What it would ask", c.questions || [])}
    ${checks(r.checks, "Passes the checks: only saved agents, and the count fits the decision.")}${foot(r)}</div>`;
}

const same = (d) => d.diff == null ? "" : d.diff.length
  ? `<div class="box warn"><b>The two runs differ:</b><ul>${d.diff.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`
  : `<div class="box good">Both runs agree on what matters: the same tools, approvals and decision.</div>`;
const pair = (d, show) => `${same(d)}<div class="pair">${d.runs.map((r, i) =>
  `<div><p class="runlabel">Run ${i + 1}</p>${show(r)}</div>`).join("")}</div>`;

const tabs = [
  ["Drafting agents", () => DATA.drafts.map((d, i) => `<section class="item"><h2>Task ${i + 1}</h2>
    <p class="typed">${esc(d.task)}</p><p class="hoped"><b>Hoped for:</b> ${esc(d.hoped)}</p>${pair(d, card)}</section>`).join("")],
  ["Room lead choices", () => `<p class="muted">In each run, the Room lead sees only the agents that run drafted and that said they can do their task.</p>` +
    DATA.choices.map((d, i) => `<section class="item"><h2>New task ${i + 1}</h2>
    <p class="typed">${esc(d.task)}</p><p class="hoped"><b>Hoped for:</b> ${esc(DECISIONS[d.hoped])}. ${esc(d.hoped_text)}</p>${pair(d, (r) => choice(r, d.hoped))}</section>`).join("")],
];
if (DATA.tries.length) tabs.push(["Your tasks", () => DATA.tries.map((t, i) => `<section class="item"><h2>Your task ${i + 1}</h2>
  <p class="typed">${esc(t.task)}</p>${choice(t.choice)}${t.draft ? `<h3>The new agent it drafted</h3>${card(t.draft)}` : ""}</section>`).join("")]);
tabs.push(["Tool list", () => `<section class="item"><p>The fixed tools an agent can pick from. Writes always need approval in Teams.</p>
  <table><tr><th>Tool</th><th>Kind</th><th>What it does</th></tr>${Object.entries(CATALOG).map(([t, [k, w]]) =>
  `<tr><td>${toolChip(t)}</td><td>${k}</td><td>${esc(w)}</td></tr>`).join("")}</table></section>`]);

function show(n) {
  document.querySelectorAll("nav button").forEach((b, i) => b.setAttribute("aria-selected", String(i === n)));
  document.getElementById("panel").innerHTML = tabs[n][1]();
}
document.getElementById("tabs").innerHTML = tabs.map(([t], i) => `<button role="tab" data-i="${i}">${t}</button>`).join("");
document.getElementById("tabs").addEventListener("click", (e) => { if (e.target.dataset.i) show(Number(e.target.dataset.i)); });

const draftRuns = DATA.drafts.flatMap((d) => d.runs).filter((r) => r.answer);
const cards = draftRuns.filter((r) => r.answer.can_do);
const choiceRuns = DATA.choices.flatMap((d) => d.runs.map((r) => ({ ...r, hoped: d.hoped }))).filter((r) => r.answer);
const both = [...DATA.drafts, ...DATA.choices];
const secs = [...DATA.drafts, ...DATA.choices].flatMap((d) => d.runs).map((r) => r.seconds || 0);
document.getElementById("meta").textContent = `Model: ${DATA.model}. Each task ran ${DATA.rounds} times. Ran ${new Date(DATA.ran_at).toLocaleString()}.`;
document.getElementById("summary").innerHTML = [
  [`${cards.filter((r) => !r.checks.length).length} of ${cards.length}`, "cards pass every check"],
  [`${choiceRuns.filter((r) => r.answer.decision === r.hoped).length} of ${choiceRuns.length}`, "Room lead choices as hoped"],
  [`${both.filter((d) => d.diff && !d.diff.length).length} of ${both.length}`, "tasks the same in both runs"],
  [`${Math.max(...secs).toFixed(0)} s`, "slowest model answer"],
].map(([b, t]) => `<div class="stat"><b>${b}</b>${t}</div>`).join("");
show(0);
</script>
</body>
</html>
"""


def main() -> None:
    results = json.loads(Path(sys.argv[1]).read_text())
    safe = lambda value: json.dumps(value).replace("</", "<\\/")  # noqa: E731
    page = PAGE.replace("__DATA__", safe(results)).replace("__CATALOG__", safe(CATALOG))
    Path(sys.argv[2]).write_text(page)


if __name__ == "__main__":
    main()
