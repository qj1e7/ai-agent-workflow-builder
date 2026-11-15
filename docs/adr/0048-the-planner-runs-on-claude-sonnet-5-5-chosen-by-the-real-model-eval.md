---
status: accepted
---

# The Planner runs on Claude Sonnet 5.5, chosen by the real-model eval

ADR 0032 started the demo on Claude Haiku 5.5 through the AI Singapore gateway, and said the eval would pick each job's model. The local app ran Claude Haiku 4.5. On 15 Nov 2026 the team lead tested the Planner by typing ordinary sentences and found the answers unacceptable. Among them was a false "you asked me to skip a yes" for a normal request that raised a ticket.

That day the eval ran against real models for the first time, through the gateway with the team lead's key (`AISG_API_KEY`). It scored Claude Haiku 4.5 and Claude Sonnet 5.5 on every golden set and on a new set of 123 "type anything" sentences, with Sonnet 5.5 as the judge. The full results, with every failing answer, are in `docs/evidence/evals/2026-11-15-baseline.md`.

| | Haiku 4.5 | Sonnet 5.5 |
|---|---|---|
| Planner golden set (`answer`) | 80% | 95% |
| Picking a workflow (`choose`) | 33% | 83% |
| "Type anything" set | 55% | 61% |
| False "skip a yes" refusals | 44 of 64 `answer` failures, 11 of 12 in the new set | none |
| Real attempts to skip a yes refused | all | all |
| Typical and slowest answer | 2.5 s and 3.7 s | 2.7 s and 4.5 s |
| Cost per 1,000 messages, at Anthropic's list prices | about $6 | about $15 |

Most of the "type anything" failures come from our rules, not the model, and both models fail them the same way. ADR 0047's free reply is the fix for those. The false refusals are Haiku's own misreading of the skip question, and Sonnet made none.

## Decision

- **The Planner uses Claude Sonnet 5.5 through the AI Singapore gateway.** It reads the request, picks a workflow and writes ADR 0047's free reply. An Operator sets it in Settings, on the Model tab, as ADR 0022 describes.
- **One model serves every job until Settings can hold one per job.** Sonnet 5.5 scored lower than Haiku on `explain` (21% against 50%) and `draft` (92% against 100%). Those sets get a closer look before the troubleshooter relies on them. When Settings can hold a model per job, the eval picks each one, as ADR 0032 says.
- **The eval stays the judge.** Every Planner change is scored against real models before it merges, with a hard cap on calls and cost per run. A model change needs a new eval run.
- **ADR 0032 still decides the model after handover.** The key is the team lead's own, and CODESparks can't keep it. The Azure OpenAI candidates must still meet the bar on each job before any Phase 2 data goes to a model.

## Considered options

- **Stay on Haiku and rely on code.** It's the cheapest. But Haiku misreads the skip question often, and the code would have to second-guess the model on every request.
- **Decide after the free reply lands.** The numbers may shift. But the false refusals are the model's own, and Sonnet's lead on the golden set is wide.
- **A model per job now.** It's the cheapest overall. But Settings holds one model today, and a per-job choice needs a change to Settings first.

## Consequences

- **Cost goes up about two and a half times.** At about 1.5 cents a message, a team of 20 people sending 20 messages a day would spend about $6 a day.
- **The slowest answers take about a second longer,** within ADR 0032's 10-second limit.
- **The gateway budget is shared and small.** The first eval runs used up the team lead's $32 budget. Eval runs now stop at a set number of calls and dollars, and a budget error from the gateway ends the run with plain words, never the raw error. The raw error named the key's owner, so the two runs that printed it were deleted.
- **The local app and Azure each switch** in Settings, on the Model tab, once the budget allows a test call.
- **`AGENTS.md`'s open decision on the model provider narrows** to the choice after handover.

## Amended 15 Nov 2026

**The Planner reaches Claude Sonnet 5.5 through Anthropic directly, with the AI Singapore gateway kept as the fallback.** The first eval runs used up the gateway's $32 budget. The team lead has a $200 monthly Anthropic credit, and added its key as the `ANTHROPIC_API_KEY` secret. Anthropic is already a known provider in Settings (ADR 0022), so the switch is made on the Model tab, with no code change. Eval runs name their Anthropic models as an input, and skip the gateway when only Anthropic models are named. Each run keeps its cap on calls and dollars. A monthly spend limit on the Anthropic console is the outer guard. Only test data reaches the model in this phase, and ADR 0032 still decides the model after handover.
