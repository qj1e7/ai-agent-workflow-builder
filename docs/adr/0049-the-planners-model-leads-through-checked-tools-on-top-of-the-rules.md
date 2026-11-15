---
status: proposed
---

# The Planner's model leads through checked tools, on top of the rules

This amends ADR 0047. ADR 0047 lets the model write a reply only where the rules reach a dead end. This ADR lets the model lead every conversation, through seven typed tools that code checks. The rules keep every refusal and build every card. It changes ADR 0047 in three places: the model picks the answer, two turns may make one request, and the free reply's facts are drawn by code. It adds no write. It does not change the approval gate, the safety checker, the word rule or the skip verdict.

## Context

The team lead's goal is that a person can type anything and get a proper, logical and useful answer (ADR 0047). The rules reach that goal one sentence shape at a time. "help me add a software" got "I didn't follow this part", and #297 fixed it with one more rule and one more amendment to ADR 0047.

A spike on 16 Nov 2026 put the model in front of the rules, behind a switch. Both modes ran once, before #297, on the same 386 messages, with Claude Sonnet 5.5 as the Planner and as the judge. The report is [2026-11-16-spike-ai-led-planner.md](../evidence/evals/2026-11-16-spike-ai-led-planner.md).

| Measure | Rules | AI-led |
|---|---|---|
| Acceptable answer | 88% | 93% |
| Judged useful, whole set | 49% | 55% |
| Judged useful, held-out third | 43% | 57% |
| Safety misses: a skip let through, a plain write refused, a done or unbuilt claim, a red-team row let through | 0 | 0 |
| Cost per message, AI-led with Anthropic's prompt cache | $0.0165 | $0.0109 |
| Time per message at the 95th percentile | 11.7 s | 12.5 s |

Message by message, 55 answers became useful and 34 stopped being useful. That is a lead from one run each (sign test p = 0.03), not proof. The spike also found three faults, which decisions 2 to 4 fix. The model ticked an ask it never did. It copied the briefing's one example reply into off-topic answers. And the content checker refused honest facts, such as a software already on the Watchlist.

## Decision

**1. The model leads, on top of the rules, and replaces nothing.** A setting, `PLANNER_MODE`, picks `rules` (today's Planner, and the default) or `ai_led`. In `ai_led`, each message goes through these steps:

- The word rule refuses first, before any model call.
- The model answers with one call to one tool. At the same time, the rules' own reading and `answer_of` read the message. If they refuse it, by the skip verdict or the coverage check, that refusal is the answer, whatever the model chose. The model can add a refusal and can never remove one.
- Code checks the call. A call that fails goes back to the model once, with the reason. A second miss shows the rules' own answer, or the I didn't follow that card when that answer is a dead end as ADR 0047 defines one.
- Every word the model writes, in its reply and in each choice, goes through ADR 0047's code checks and then the verifier, and fails closed. The model writes no row of a card.

Each tool ends in a kind of Planner answer the Portal already draws. Decision 4 adds one field to the free reply.

| Tool | Answer | What code checks |
|---|---|---|
| `set_up_workflow` | The rules' own card, can't or refusal | Every word is the person's. The rules' reading and `answer_of` build the card. |
| `watch_software` | Watchlist row | The person typed the name, and the Watchlist doesn't hold it. |
| `ask_which_software` | Which software | Nothing |
| `change_workflow` | Edit, pause or resume | Operators only. The workflow words are the person's. A day or a time must be the one `said_schedule` reads in their words. |
| `show` | Check workflows, why it stopped, what needs me, How to start, or what it can do | The workflow words are the person's. |
| `refuse_skip` | Refusal | The quoted words are in the message. |
| `reply` | Free reply | ADR 0047's code checks, then the verifier |

When the model picks `watch_software` or `change_workflow` and the rules read the same kind, the person sees the rules' answer.

**2. Code checks every tick.** A one-action tool ticks only the clauses its own arguments reach. Those are the clause that names the software, the clause with the workflow words and the schedule, the clauses the rules' own marks give a state answer or How to start, and the only clause of a one-clause message. Every other clause is crossed with Ask this on its own, which sends it as its own message. Nothing the model lists, or leaves out, can tick a clause. In the spike, "Add Kubernetes to the watchlist and tell me what needs me" showed the second ask as done, because code trusted the model's list of other asks. A cross the person can tap is better than a false tick, so a clause in doubt is crossed.

**3. The briefing states rules and never shows a reply to copy.** It holds what each tool is for, ADR 0047's rules for a reply, the capability registry and the how-to guide. It may show what a person types and which tool fits. It never shows a sentence of a reply. In the spike, the briefing's one example can't ("The nearest thing is a weekly list of open bugs in one new Jira ticket") came back for a translation, a meeting room and lunch. Off-topic answers judged useful fell from 8 of 8 to 3 of 8. The briefing's fixed part stays the same for every message, so the prompt cache keeps it.

**4. Code draws the facts, so the claim checks stay as strict.** In the spike, true answers about the person's own data fell back. "LangGraph is already on the Watchlist" failed ADR 0047's third check, which refuses a claim that something happened. "With a ticket waiting for an Approver's yes", true of FastAPI, made the verifier answer that something is already happening. And a correct answer to "Redis", after "Which software should I watch?", ended "To add another one, type its name", which the verifier refused as a claim of an unbuilt ability. Two things change, and no check gets looser:

- The free reply gains `about`, the names of the watched software and workflows it speaks of. Code keeps a name only if the facts hold it. The Portal draws each one's state line from the facts, as it does for a question answer (ADR 0042). The briefing tells the model to name the thing and say what to do next, and to leave versions, states and runs to that line. The checks don't change, so a state the model restates may still be refused.
- A sentence that only says a list holds something, as "Your Watchlist already holds Redis", is no claim. Check 3 already lets "holds" through. The verifier's prompt gets one more line that says so, beside its other "no" cases.

The verifier serves both modes. The red-team set must still flag every row it flags today, and honest rows with these wordings join it as rows that must show. The third fault needs no change of its own, because #297 added a line on adding software to the how-to guide, which the verifier reads. The runs in decision 6 check it again.

**5. Two turns may make one request, and no more.** #297 already takes a software name from the message after "Which software should I watch?". In the same way, `set_up_workflow` may join the turn before and the message into one request. It may do so only when the turn before ended in the Planner's own question: which software, a clarifying question, or a card with a part to fill. Every word of the joined request must be one the person typed in those two turns, glue words aside, and never one of the Planner's. The joined text then goes through the word rule, a fresh reading, the skip verdict and `answer_of`, as if typed whole. Three turns are never joined.

The Portal sends the turn before, so a client can forge it (ADR 0047). A forged turn can only put words in the joined request that its sender could type in one message, and that request meets every check a typed one meets. It can't skip a yes, make a card claim what the rules don't hold, or change the facts. Every write still waits for an Approver's yes at the write gateway (ADR 0026). It can still move the model's tone. In the spike, a planted turn before led to a reply that began "Please disregard my last answer, because it was wrong." The reply claimed nothing and passed both checks. The checks catch claims, not tone, and that stays a known gap. Keeping the turn on the server would close it, and needs its own ADR.

**6. The default switches after three runs per mode.** The eval draws each answer with the marks it carries. Each mode runs three times on the `reply`, `anything` and spike sets, on one day, with the same model and judge. `ai_led` becomes the default only when every bar holds:

| Measure | Bar |
|---|---|
| Safety misses, with every judged 1 read by hand | 0 in every run |
| A clause ticked that no tool argument reaches | 0 in every run |
| Acceptable answer | At least 93% in every `ai_led` run, and no lower than the best `rules` run |
| Judged useful (4 or 5) | The worst `ai_led` run beats the best `rules` run, on the whole set and on the held-out third |
| Time per message at the 95th percentile | 13 s or less, with every model call within ADR 0032's 10 s at the 95th percentile |
| Cost per message at list price | No more than `rules` in the same runs |

At the spike's rates, the six runs cost about $52 from the team lead's monthly credit (ADR 0047). The team lead reads the runs and decides the switch. Until then, `ai_led` runs only where the team lead turns it on. Going back is one setting, `PLANNER_MODE=rules`.

## Considered options

- **Rules only, as today.** Code writes every answer, so nothing new can go wrong in the words. But each new sentence shape needs a rule, as #297 shows. The spike also found the rules telling people "I can't add Terraform to the Watchlist yet", though adding software is Ready.
- **The model in place of the rules.** This deletes the most code. But the model would write the cards and decide the refusals. ADR 0047 rejected that, because a card must claim only what code will run. The spike never tested a model in place of the skip rule.
- **The model on top of the rules (chosen).** It answers more messages well, keeps every refusal and card in code, and costs less per message with the prompt cache. Its costs are a second prompt to keep, one more model call beside the reading, and the gap in decision 5.
- **A separate agent responsible for the contents of the chat.** This was the team lead's idea. Its safe part exists already: the verifier is a narrow model call that reads every reply and can only refuse it. An agent that rewrote or approved replies would add a call to every message, and a model checking a model is a filter, not a proof (ADR 0047). The spike's faults were a false tick and checks that read facts as claims, and code fixes both better than another model.

## Consequences

- **Cost and time.** Each message makes the model's call beside the reading. The prompt cache makes that cheaper than `rules` today. Without the cache, as at a model address that isn't Anthropic's, `ai_led` costs about $0.031 a message at Sonnet 5.5's list price, nearly twice `rules`.
- **One more prompt to keep.** The briefing reads the registry and the guide, so it changes when they do. Its rules go through the same eval as ADR 0047's.
- **The shaping rules can go later.** Once `ai_led` is the default, a rule that only shapes helpfulness can be deleted when the eval shows the model does as well on its cases, as ADR 0047 planned. The word rule, the skip verdict, the coverage check and the cards stay.
- **The glossary changes if this is accepted.** It gains "AI-led Planner", and "Planner answer" says the model picks the tool.
