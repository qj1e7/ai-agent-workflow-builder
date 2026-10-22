# Decision memo: which AI model provider

This memo says what should decide the choice. It does not make the choice. The scores are in [README.md](README.md). So far only the two local Ollama models have run. Every cloud provider is "not run" until the team lead adds a key.

## 1. Quality per job

A model only earns its place where it beats what the code already does.

- **Summarise.** The runtime's own template sentence ("2 new releases: 1.2.16, 1.2.15") passes every summary check. A unit test proves it. So a model adds value here only if people prefer its wording, and the optional LLM judge or a human read is the way to find that out. A model that misses a version, or answers too slowly, is worse than the template. The product falls back to the template after 10 seconds.
- **Explain a failure.** Today a fixed rule table answers, written by us in plain words. A model is worth it if it explains the specific run better: which system failed, what the Operator should do, and whether a retry is safe. Watch `retry_safe_matches` most closely. A wrong "retry is safe" is the costly mistake.
- **Match a task to a template.** Today a keyword match answers. The model's value grows with the number of templates. With one template, a model mostly has to say "none of these" for unrelated requests and not make up a project key.

Ask for each candidate: the pass rate per job, the check that fails most, and whether the failures are the costly kind (a wrong retry answer, an invented value, a claimed write) or the cosmetic kind (one jargon word).

## 2. Cost on Azure for Students credits

Hosting runs on Azure for Students credits. So the first question is whether a model can be paid from those credits at all. Azure OpenAI is billed to the Azure subscription. Anthropic and Google are billed to their own accounts, unless they are used through a marketplace offer on Azure.

The traffic is small. A release check runs a few times a day, and an explanation runs only when a run fails. Even at a few cents per 100 calls, cost is unlikely to decide this. Credit limits and quota (requests per minute on a student subscription) are more likely to. Fill in `pricing.json` for each cloud model you test, so the "$/100 runs" column has a number with a dated source.

## 3. Data residency for DevNet

CODESparks runs in DevNet, the NCS private network. Two questions decide which providers are allowed there:

- Can DevNet reach the provider's endpoint at all, and in which region does the data land?
- What does the data contain? The MVP sends public release tags. Phase 2 sends access-review data (names, groups, admin rights). That is internal data, and NCS policy decides where it may go.

A self-hosted model answers both questions, because nothing leaves the network. Azure OpenAI in a Singapore or other approved region may also pass. We need the answer from the sponsor in writing before Phase 2.

## 4. Is a self-hosted model enough?

Two runs on the laptop give a first answer for small local models. Both runs scored the same, and every answer was the same word for word:

| Model | Summarise | Explain | Match |
|---|---|---|---|
| `gemma:2b` (3B, 4-bit) | 1/12 | 3/13 | 0/13 |
| `deepseek-r1:latest` (8B, 4-bit, thinking) | 11/12 | 7/13 | 11/13 |

An earlier run scored `explain` one lower for each model (2/13 and 6/13). The answers were the same. A check was too strict about who declined a run, and we fixed it. The README explains this, and lists the checks that may still be too strict.

`gemma:2b` is not enough:
- It refuses 11 of the 12 summaries ("I do not have access to real-time project updates"), even though the prompt gives it the tags.
- It never picks a template. It copies the example values from the template list (`langchain-ai/langgraph`, `MOCK`) into every answer, even for a meeting room booking.
- It says a retry is not safe every time, so its right answers on retry are luck.

`deepseek-r1` is close on summaries and matching:
- **Summarise.** One summary leaves out the version ("There is a new release of langgraph available."). The product would still show it, because it only checks the length and the line breaks.
- **Match.** It misses the starting tag in a casual sentence ("anything newer than 0.115.0"). It also keeps the `v` in `v1.9.8`, which the builder would refuse.

It falls short on plain-language explanations:
- Three answers repeat a code or status: `503`, `write_action` and `create_page`.
- Two leave out that the request was approved before Jira failed.
- One says a retry is not safe when it is. That is the cautious mistake, not the costly one.

It is also slow. The median summary took 5 to 6 seconds. Three of the 12 summaries took over 10 seconds, and the slowest took 30 to 34 seconds. The product gives up on the model after 10 seconds and uses its template, so in the product those three would be the template sentence. Its explanations and matches took about 8 seconds each.

So the open questions for a self-hosted route are:

- Does a larger local model, such as 14B to 32B, clear the explain job? It needs a GPU server inside DevNet, which costs money and needs someone to run it.
- Does the best cloud model score much higher? If it does, the gap tells us what self-hosting gives up.

## What would settle it

1. Run the bake-off on at least one Azure OpenAI deployment and one other cloud model.
2. Compare pass rates per job against `deepseek-r1`, and read the failing answers, not only the rates.
3. Get the sponsor's written answer on which providers DevNet may call, and for which data.
4. Then pick, per job if that is simpler. The template summary may stay, a model may explain failures, and matching may wait until there are more templates.
