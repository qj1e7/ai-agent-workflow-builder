"""PROTOTYPE 2, throwaway. Turns card-runs.json into one HTML file you can double-click."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render import PAGE  # noqa: E402

STYLE = PAGE.split("<style>")[1].split("</style>")[0]

RUNS_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Card runs prototype</title>
<style>__STYLE__
.marks { list-style: none; padding: 0; margin: 10px 0 0; }
.marks li { padding: 2px 0 2px 24px; position: relative; font-size: 14px; }
.marks li::before { position: absolute; left: 0; font-weight: 700; }
.marks li.ok::before { content: "✓"; color: var(--good); }
.marks li.no::before { content: "✗"; color: var(--bad); }
.marks li.no { color: var(--bad); }
.steps { margin: 0; padding-left: 22px; font-size: 14px; }
.steps li { margin: 0 0 6px; }
.result { color: var(--muted); font-size: 12px; word-break: break-word; }
.said { white-space: pre-wrap; background: var(--bg); border-radius: 8px; padding: 10px 12px; font-size: 14px; margin: 6px 0; }
</style>
</head>
<body>
<main>
  <span class="tag">Throwaway prototype, not the product</span>
  <h1>Card runs prototype</h1>
  <p class="muted" id="meta"></p>
  <div class="question">
    <p><b>The question:</b> when an agent runs a saved card, does it follow the plan, stay inside its tools,
    and make proposals that pass our safety checker? Does text planted in the data change what it proposes?</p>
    <p class="muted">GitHub reads are real, except one made-up repository. Jira is a small stand-in held in memory.
    Writes are only proposals: they go through the platform's own target binding and safety checker, with Bob
    approving. Nothing is written anywhere.</p>
  </div>
  <div class="summary" id="summary"></div>
  <div id="panel"></div>
</main>
<script>
const DATA = __DATA__;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (o) => esc(Object.entries(o || {}).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", "));

function run(r) {
  if (r.error) return `<div class="box bad"><b>The run failed:</b> ${esc(r.error)}</div>`;
  const marks = `<ul class="marks">${r.marks.map(([ok, t]) => `<li class="${ok ? "ok" : "no"}">${esc(t)}</li>`).join("")}</ul>`;
  const steps = `<h3>What it did</h3><ol class="steps">${r.timeline.map((s) => `<li><span class="tool ${s.tool.includes("create") || s.tool.includes("post") ? "write" : ""}">${esc(s.tool)}</span>
    ${short(s.input)}<div class="result">${esc(s.result)}</div></li>`).join("")}</ol>`;
  const g = r.gate;
  const approver = g.actions ? `<h3>What the Approver would see</h3>${g.actions.map((a, i) => `<p><b>${esc(g.lines[i])}</b></p>
    <div class="said">${esc(Object.entries(a.fields).map(([k, v]) => `${k}: ${v}`).join("\n\n"))}</div>`).join("")}` : "";
  const box = g.passed === null ? `<div class="box good">${esc(g.result)}</div>`
    : `<div class="box ${g.passed ? "good" : "bad"}">${esc(g.result)}</div>`;
  return `${marks}${steps}${approver}${box}
    ${r.report ? `<h3>Its report to the staff member</h3><div class="said">${esc(r.report)}</div>` : `<div class="box bad">${esc(r.stopped)}</div>`}
    <p class="foot">${r.turns} turns, ${r.seconds} s, ${r.tokens[0]} tokens in, ${r.tokens[1]} out</p>`;
}

document.getElementById("panel").innerHTML = DATA.cases.map((c, i) => `<section class="item">
  <h2>${i + 1}. ${esc(c.title)}</h2>
  <p class="muted">Card: <b>${esc(c.card)}</b>. Inputs: ${short(c.values)}</p>
  <p class="typed">${esc(c.setup)}</p>
  <p class="hoped"><b>Should:</b> ${esc(c.should)}</p>
  <div class="pair">${c.runs.map((r, n) => `<div><p class="runlabel">Run ${n + 1}</p>${run(r)}</div>`).join("")}</div>
</section>`).join("");

const runs = DATA.cases.flatMap((c) => c.runs).filter((r) => !r.error);
const marks = runs.flatMap((r) => r.marks);
const gated = runs.filter((r) => r.gate.passed !== null);
document.getElementById("meta").textContent = `Model: ${DATA.model}. Each case ran ${DATA.rounds} times. Ran ${new Date(DATA.ran_at).toLocaleString()}.`;
document.getElementById("summary").innerHTML = [
  [`${runs.filter((r) => r.marks.every(([ok]) => ok)).length} of ${DATA.cases.length * DATA.rounds}`, "runs did everything right"],
  [`${marks.filter(([ok]) => ok).length} of ${marks.length}`, "checks passed"],
  [`${gated.filter((r) => r.gate.passed).length} of ${gated.length}`, "proposals pass the safety checker"],
  [`${Math.max(...runs.map((r) => r.seconds)).toFixed(0)} s`, "slowest run"],
].map(([b, t]) => `<div class="stat"><b>${b}</b>${t}</div>`).join("");
</script>
</body>
</html>
"""


def main() -> None:
    results = json.loads(Path(sys.argv[1]).read_text())
    safe = json.dumps(results).replace("</", "<\\/")
    Path(sys.argv[2]).write_text(RUNS_PAGE.replace("__STYLE__", STYLE).replace("__DATA__", safe))


if __name__ == "__main__":
    main()
