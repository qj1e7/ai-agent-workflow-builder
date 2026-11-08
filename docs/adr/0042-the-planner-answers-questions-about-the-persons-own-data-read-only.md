---
status: accepted
---

# The Planner answers questions about the person's own data, read-only

This amends ADR 0037, which says the reply text is fixed. It changes that for one answer. It adds no write and does not touch the approval gate or the safety checker.

## Context

A staff member types "help me check how many software in the watchlist" on Home. The Planner replies with the list of what it can do. ADR 0037 has the model only fill a reading, and code picks one answer with fixed text. None of those answers says "tell me about my data", so a plain question about the Software page, the Workflows page or Needs you gets the wrong reply. We found this on 8 Nov 2026. The Planner must answer plain questions about the person's own data, or the box on Home looks broken.

## Decision

**A question about what the platform holds for the person gets an answer in the model's own words.** The first reading is unchanged: the model still fills the same reading, and code still picks the fixed answer from it. The lane replaces two of the dead ends that answer reaches. One is the catch-all, the abilities list, which a plain question about the Software page, the Workflows page or Needs you lands on. The other is the offer to watch a software the watchlist already holds, such as "Is there a newer version of LangGraph?" when LangGraph is on the list. In those two cases, and only when the platform sent facts, code asks the model once more, with the question and a facts snapshot as JSON. The reply says first whether the question is about the person's own data. If it is not ("What can you do?"), the fixed answer stands. If it is, the reply is a `question` answer: its text (600 characters at most) and `looked_at`, the sections it used (`watchlist`, `workflows`, `needs_you`).

**The facts are read when the question arrives, by the code the screens use.** platform-api builds them from the Software page's rows, the Workflows page's workflows and newest runs, and the counts Home shows under Needs you. The Software and Workflows facts are the team's, as those pages are. Needs you is the signed-in person's. A section that cannot be read, or would not fit the cap (100 software, 50 workflows), is left out.

## The guards

- **Read-only.** The lane has no tool and no write. The facts are a copy, and the reply changes nothing.
- **Facts only.** The model may use only the facts, and counts from them. If they do not hold the answer, it says so in one sentence.
- **No offers.** The reply may not say what the platform can or will do, or offer to set something up or act. Code checks the reply for such phrases, and for length.
- **Sources shown.** Code keeps only the sections that were really sent. The Portal shows them as "Looked at", linked to the screens.
- **A fixed fallback.** If the facts are missing, or the reply offers to act or runs long, the answer is the fixed text "I couldn't answer that from what I can see." with no sections.

## Routes added for the watchlist (8 Nov 2026)

The first reading stays as it is. Everything below is code routing, the lane's own prompt, or the Portal. A change to the first reading moved unrelated answers on 8 Nov, so it is off limits.

**More fixed answers can reach the lane.** Each keeps the same escape: if the lane says the question is not about their data, or its call fails, the first answer stands.

- **2a. Which software.** A request that is a question goes to the lane when the facts hold at least one watched software. A question ends with "?" or starts with which, what, how, is, are, do, does, did or when. "Tell me when there's a new version" is not a question and stays "which software".
- **2b. The three state answers.** The reading often takes a question about the watchlist for one about workflows. "When did it last check?" reads as check my workflows, "Did it open a ticket for Redis?" as why did it stop, and "Is anything waiting for my yes?" as what needs me. Only Check my workflows, and only when the request names the watchlist (the words watchlist, watching or watched), goes to the lane, whatever its shape. "Why did ... stop?" and "What needs me?" keep their fixed answers, the AI troubleshooter link and the Needs you list with its buttons, so a question like "Is anything waiting for my yes?" gets the Needs you list. One more route: "Did it open a ticket for Redis?" reads as why did it stop, and goes to the lane when the facts carry workflows and none of their last runs is Stopped, because the fixed answer then has nothing to show; a stopped run, or missing facts, keeps the AI troubleshooter link. A follow-up ("and LangGraph?") is rewritten only from an earlier request that is shaped like a question and passes the word rule, and the word rule runs again on the rewritten text.
- **2c. A reply the guards reject.** On the watched-software offer, which software and the state answers, a reply the guards reject returns the first answer, not the fixed text. Only the catch-all keeps "I couldn't answer that from what I can see."

**More facts per software.** Each watched software now carries when it was last checked, its open ticket, whether a ticket waits for a yes, why the last check failed, and how the version the team runs was set (given, first check or a ticket marked Done, with the ticket). They come from the same row the Software page shows, so one fact has one source. The lane can answer "When did it last check?", "Did it open a ticket for Redis?" and "Is anything waiting for my yes?".

**Follow-ups are context for the question lane only.** The Portal sends the previous turn with the next typed request: its words, the software the Planner named, and the text it answered with. Only the question lane's prompt reads it, as read-only context to understand a short question such as "and X?". The Planner never builds request text from an earlier turn: the first reading, the word rule and every fixed answer see only what the person typed. Two checks showed that swapping a name into an earlier request can produce text the person never typed, such as "Upgrade Redis without approval" followed by "and LangGraph?". The safe follow-ups below are the only other use of the previous turn.

**Waiting words.** While an answer is pending the Portal says "Working on it…". After 8 seconds it says "Still working. Questions about your data take a little longer." It names no step, because none is known (principle 8).

## One-tap actions under the answer (8 Nov 2026, step 2b)

The lane's reply names the watched software it is about (`about_software`). Code keeps a name only when the watchlist facts hold it and the answer's text mentions it, spelled as the watchlist spells it, three at most. A count or a list of the whole watchlist names none.

Under such an answer the Portal shows the Software page's own actions to an Operator and to no one else. They are Open (the row on the Software page), Check all software now (the Software page's Check now, which checks the whole watchlist, so the button says so), and last, Stop watching. Stop watching asks first, then runs the Software page's remove, and its Undo is the page's restore (principle 3). The actions use the same Portal calls and the same platform-api routes as the Software page. No route is added, and the approval gate and the safety checker are not touched. An Approver sees none, as on the Software page. Unwatched software keeps the offer card.

## Safe follow-ups (8 Nov 2026, step 2b)

The Portal sends the kind of the previous answer with it (`previous.kind`). It is client input, so it only decides whether a follow-up applies, and it is lane context. A follow-up applies when the previous kind is `question` or `watchlist`, the facts hold a watchlist, and the typed text is "and X?", "what about X?" or "how about X?" with X a plausible name: one to three words, no pronoun or question word, no change verb, nothing the word rule refuses.

- X is on the watchlist: the typed words go to the question lane with the previous request and answer as context. The first reading still runs on the typed words alone. If the lane says no or fails, the first answer stands.
- X is not on the watchlist: the answer is the offer to watch X, with the word "version". The person must tap it, so nothing is written.
- Anything else takes the normal path.

Request text is never built from an earlier turn. A forged `previous` such as "Upgrade Redis without approval" changes nothing but the lane's prompt, or the offer card the person must tap.

## What stays fixed

Set-up cards, parts, can'ts, refusals, "which software", offers to watch software the watchlist does not hold, "what can you do" and the chips keep their fixed text. A request that asks for a change stays a task even when it also asks a question, so no part of it is dropped. The approval gate, the safety checker and the word rule for skipped yes answers are unchanged.

## Not now

Questions about Jira tickets get no answer from this lane in this phase. A search still becomes a set-up card. A read of live Jira for an answer needs its own decision.

## Considered options

- **Fixed text per question kind.** Safe, but each new question needs new code and text, and a count or a version lookup cannot be fixed text.
- **Let the model call tools.** It could answer anything, but it would need a read tool per source and a way to keep it from writing. The snapshot is smaller and cannot write.
- **Teach the first reading a new kind, `my_data`.** We tried this. It moved unrelated answers in the eval, so "Tell me when there's a new version" became a can't and a Jira count became a question. Routing in code leaves the first reading alone.
- **Send the facts with the first call.** One call less, but the model would see the data on every request, including tasks.

## Consequences

- A typed request that is a question costs a second model call, so the platform's limit around the answer is 20 seconds, up from 10.
- The facts go to the AI model provider. They are names, versions and counts the team already keeps on its pages.
- The eval set gains cases for the routing, including each Home chip. The first reading is unchanged, so the cases that passed before still do. The reply guards are covered by unit tests and a live check.
- The glossary gains "Question answer".

## Decision record

Accepted by the user on 8 Nov 2026: a read-only question lane, with the guards above.
