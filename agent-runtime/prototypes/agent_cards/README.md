# Agent cards prototypes (throwaway)

These are throwaway prototypes, not product code. They live only on the branch `prototype/agent-cards` and never merge to `main`. They answered two questions before ADR 0023.

Both prototypes run inside the local `platform-api` container. That way the AI key an Operator saved in the Portal is opened there and never printed. They call the model saved in Settings, Claude Haiku 5.5 through the AI Singapore gateway. Run them with the local stack up (`scripts/up.sh`).

## 1. Can the model draft good agent cards?

```
agent-runtime/prototypes/agent_cards/run.sh ["a task of your own" ...]
```

The script drafts a card for each of 5 tasks, twice. Then the Room lead chooses saved agents for 4 new tasks.

- **Pages:** `out/agent-cards.html` is the fixed prompts. `out/v1-agent-cards.html` is the first try.
- **Verdict: yes.** Cards took 3 to 8 s. The model used no tool outside the list and made up no projects or people. It asked questions instead.
- **The first try added its own approval steps** and chose who approves. Once the platform owned both, 6 of 8 cards passed every check.
- **The 2 that still failed are both the access review.** Each time it asked managers in Teams without an approval. The team decided to approve that list once per run.
- **The main plan was stable between runs; the extras varied.** That is fine, because a person reviews a card once and runs use the saved card.
- **Still open:** the Room lead mixes up "can't do" with "new agent".

## 2. Does an agent follow a saved card?

```
agent-runtime/prototypes/agent_cards/run_cards.sh
```

It runs two saved cards (`saved_cards.json`) on 4 cases, twice each. GitHub reads are real, except one made-up repository; Jira is an in-memory stand-in. Writes become proposals and go through the platform's own `bind()` and `check()`.

- **Page:** `out/card-runs.html`.
- **Verdict: yes.** All 8 runs did the right thing, and all 46 checks passed. Every proposal passed the safety checker with Bob approving, and approval by the person who started the run was refused.
- **The agents ignored planted instructions** in release notes and in a Jira comment, and warned the Approver.
- **Gaps it found:**
  - The agent has no memory of its last run.
  - The approval text for a Teams post is only "post_message on teams".
  - A card must say which input fills each write's target.
- **Gateway cache:** the AI Singapore gateway returns a stored answer for a byte-identical request. Repeat runs one after another measure the cache, so these runs were sent in parallel. `out/card-runs-first.json` holds the independent runs that `out/card-runs.json` re-judges.
