# Checks for the UX redesign

These scripts measure a clickable prototype, so version 3 and version 4 are compared with the same ruler. Run them from the repository root. They use the Playwright that `portal/` installs.

## Commands

```
node docs/design/ai-native-redesign/checks/run.cjs <prototype.html> <paths.cjs> <out.json>
node docs/design/ai-native-redesign/checks/shots.cjs <prototype.html> <paths.cjs> <outdir>
node docs/design/ai-native-redesign/checks/quality.cjs <prototype.html> <paths.cjs> <out.json>
```

Version 3 baseline:

```
node docs/design/ai-native-redesign/checks/run.cjs docs/design/portal-routines/prototype.html docs/design/ai-native-redesign/checks/paths-v3.cjs docs/design/ai-native-redesign/checks/results/v3.json
node docs/design/ai-native-redesign/checks/shots.cjs docs/design/portal-routines/prototype.html docs/design/ai-native-redesign/checks/paths-v3.cjs docs/design/ai-native-redesign/screenshots/before
node docs/design/ai-native-redesign/checks/quality.cjs docs/design/portal-routines/prototype.html docs/design/ai-native-redesign/checks/paths-v3.cjs docs/design/ai-native-redesign/checks/results/v3-quality.json
```

`run.cjs` takes about two minutes. Add `--only=A,T5,B@390` to run some scenarios.

`home-weight.cjs` needs no arguments. It counts the words, visible controls and primary buttons on Home in both versions, on a normal week and on day one, and writes `results/home-weight.json`.

## What each output means

**run.cjs** writes the JSON and a table next to it (`v3.md`). For every scenario it gives the id, the width, pass or fail, the first failed assertion with the value it found, and these counts:

- `clicks`: a click or key press on a button or link, including menu steps.
- `fields`: one per text box filled, not per character.
- `selects`: a dropdown or segmented choice.
- `navs`: a click that changed the page. It is also in `clicks`. The runner detects it from the page address.
- `decisions`: a step tagged as a choice the user has to think about. It is also a click, a select or a field.
- `screens`: distinct pages visited.
- Extra numbers a scenario records, such as `plannerQuestions`.

Test controls (switching person, Day one, "Make something happen") go through `t.setup(...)` and are never counted. The JSON also has the ordered step log and any page or console errors. A page error fails the scenario.

`CONTROL-must-fail` is added by the runner. It asserts text that is not on the page and must fail. The run prints a warning if it passes, because then the checks cannot be trusted. It is reported apart from the real scenarios and does not count in the totals.

A scenario with `notPossible: 'reason'` is skipped and reported as not possible. It is never a pass.

**shots.cjs** writes `<name>-desktop.png` (1280 by 1000) and `<name>-phone.png` (390 by 844), full page, light theme, with the test controls and messages hidden. It waits for the Planner's typed reply first. It loads the web font from the internet.

**quality.cjs** writes, for each screen at both widths: axe-core violations by impact, whether the page scrolls sideways at 390 px (with the widest elements), the running animations under reduced motion, and console errors. It also counts the Tab presses from page load to the Home text box (Operator) and to Bob's first "Review and decide" button, and lists stops with no visible focus style.

**fit.cjs** checks that the layout holds at 1440, 1280, 1024, 861, 768 and 390 px, on every screen. It reports four kinds of problem:

- Text that sticks out of the card, box, button or pill that holds it.
- Text cut off by a box that hides overflow, or shortened with an ellipsis.
- Two pieces of text drawn on top of each other.
- Buttons side by side that differ in height or sit off each other's centre.

It also reports sideways scroll and console errors. Text past a scrolling area counts as reachable, and a layer fixed to the screen is measured on its own. A seeded control must be caught first, so the check is known to fail when it should. Text inside SVG (the n8n canvas) is not measured, so look at the screenshots for it. Run it with `node docs/design/ai-native-redesign/checks/fit.cjs <prototype.html> <paths.cjs> <out.json>`. Add `--widths=1280,390` or `--only=name,name` for a shorter run. It exits non-zero on any problem.

## Add a version's paths

1. Copy `paths-v3.cjs` to `paths-v4.cjs`.
2. Keep the scenario ids (`A`, `B`, `C`, `C-self`, `D` to `H`, `T1` to `T15`). Change the steps and selectors to the new design. Add new ids for new tasks.
3. A scenario is `add(id, title, async (t) => { ... }, [widths], extra)`. Use `t.click`, `t.press`, `t.field`, `t.select`, `t.ask`, `t.menu` for what a user does, `t.setup` for test controls, and `t.expect`, `t.expectText`, `t.expectCount` for the outcome. Tag a thinking step with `{ decision: true }`. Use `{ reply: true }` to wait for the Planner's typed reply and `{ until: /text/ }` to wait for a run to finish.
4. Update `screens` (each has `prepare(k)`), `keyboard` (the two targets for the Tab check) and, if the page address changes, add `screenOf(page)` and `menu(width, name)` exports.
5. Run the three commands with the new prototype and a `v4` name.

## Limits

- A screen is the first part of the address hash (`home`, `workflows`, `run`). If version 4 changes the hash, export `screenOf`.
- The Bob keyboard check cannot reload, because the person is chosen in the test controls. It resets the focus start to the top of the page instead.
- Full-page phone shots show a fixed tab bar once, where the page was when the shot was taken.
- The runs block the web font so they do not depend on the network. shots.cjs and quality.cjs do not, so their numbers can shift a little offline.
