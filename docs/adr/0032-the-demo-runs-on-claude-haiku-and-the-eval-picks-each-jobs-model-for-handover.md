---
status: proposed
---

# The demo runs on Claude Haiku 5.5, and the eval picks each job's model for handover

The AI model provider has been open since the start, to be decided by testing (ADR 0017). The rebuild adds jobs that need a model. The Planner must read a task and say what it understood. The AI troubleshooter must explain a failed run, and today a fixed rule table does that. The evidence so far points one way:

- **Claude Haiku 5.5, through AI Singapore's gateway.** In the agent cards prototype it drafted cards in 3 to 8 seconds, used no tool outside the list and made up no project, page or person. Once the platform owned the approval steps, 6 of 8 drafts passed every check. 8 of 8 runs of two saved cards did the right thing, and all 46 checks passed. It ignored instructions planted in release notes and a Jira comment, and it warned the Approver about them. The record is in ADR 0023 and on the `prototype/agent-cards` branch.
- **Local models through Ollama.** `deepseek-r1` (8B) scored 11 of 12 on summaries and 11 of 13 on matching, but only 6 of 13 on explaining a failure. Its slowest summaries took over 30 seconds. `gemma:2b` failed almost every case. The [bake-off](../evidence/model-bakeoff/README.md) has the numbers.
- **Azure OpenAI, Anthropic direct and Google Gemini** have never run, because no key was set.

ADR 0021 already uses the AI Singapore gateway for the November demo. Its key belongs to the team lead's AIxTech subscription, so CODESparks can't keep it after handover. So this ADR settles the demo and sets the rule for handover:

- **The first demo uses Claude Haiku 5.5 through the AI Singapore gateway,** connected in Settings as ADR 0022 describes.
- **First, Haiku 5.5 sets the bar.** We score it on every golden set in `agent-runtime/evals/cases`: summarise, explain, match, draft and choose. We add an `understand.json` set for the Planner, built from the prototype's tasks and the rows it shows back. The gateway returns a stored answer when it gets the same request twice. So repeated cases go out at the same time, or carry a marker for each run.
- **The handover candidates are Azure OpenAI models in Southeast Asia.** The first is `gpt-5.4-mini` as Data Zone Standard, which keeps processing inside Asia Pacific. The second is `gpt-5-mini` as Global Standard, which may process prompts in any Azure region, so it stays a candidate only if the sponsor allows that. Microsoft's region list on 29 Oct 2026 offers both in Southeast Asia. CODESparks runs on Azure, which keeps the bill and the data under NCS's own subscription.
- **The eval picks a model for each job.** A candidate qualifies for a job when it makes none of the costly mistakes on that job's golden set: a wrong "retry is safe", an invented project or person, or a claimed write. It must also match Haiku's pass rate within one case, and answer within 10 seconds at the 95th percentile. Of the models that qualify, the cheapest wins. A job that no candidate passes keeps its template or rule table. The sponsor's written answer on which providers DevNet may call can rule a candidate out.
- **We decide before any Phase 2 data goes to a model.** The access review sends internal data, so the model it uses must be chosen and the sponsor must have agreed in writing.

## Considered options

- **Pick Azure OpenAI now, because the platform is Azure-first.** It may well win. But it has no score yet, and community reports say student subscriptions start with no Azure OpenAI quota. A pick with no evidence breaks ADR 0017's rule.
- **Keep Haiku 5.5 through the gateway after handover.** It has the best evidence. But the key is the team lead's own, and the gateway may not be reachable from DevNet.
- **Host a model inside DevNet.** Nothing would leave the network. But the 8B model fails half of the explanations, and a larger one needs a GPU server that someone has to pay for and run.
- **One model for every job.** It is simpler to set up. But summaries already pass with a template and no model, and a per-job choice lets the cheap jobs stay cheap.

## Consequences

- **This extends ADR 0021 past the demo, and gives ADR 0017's bake-off a rule.** Scores, failing answers and the dated price list go in `docs/evidence/model-bakeoff/`.
- **Azure OpenAI joins the known providers** in `platform-api/src/platform_api/orchestration/model_settings.py`, through a reviewed PR as ADR 0022 requires, after the first presentation. Today the list is `aisg`, `openai`, `anthropic` and `gemini`, while the prototype already shows Azure.
- **Quota is the first risk.** Someone requests Azure OpenAI quota on the subscription that will run the eval before the eval is due. If the student subscription gets none, the eval runs on a subscription NCS provides.
- **Keys never sit in git.** The eval runs through `evals.yml`, with keys in its `evals` environment, or on a team member's machine through `scripts/evals.sh`. The results are saved as evidence, with keys removed, as the eval code already does.
- **The AI usage tab needs token counts.** Every model call records the tokens its answer reports, by workflow, and a price list in git turns them into cost. That is Phase 2 work, with the usage limit.
- **The Planner and the troubleshooter get model versions with a fallback.** Without a model, or after 10 seconds, the Planner falls back to the starter workflows, and the troubleshooter falls back to its rule table.
