---
status: accepted
---

# The Planner answers questions about the person's own data, read-only

This amends ADR 0037, which says the reply text is fixed. It changes that for one answer. It adds no write and does not touch the approval gate or the safety checker.

## Context

A staff member types "help me check how many software in the watchlist" on Home. The Planner replies with the list of what it can do. ADR 0037 has the model only fill a reading, and code picks one answer with fixed text. None of those answers says "tell me about my data", so a plain question about the Software page, the Workflows page or Needs you gets the wrong reply. We found this on 8 Nov 2026. The Planner must answer plain questions about the person's own data, or the box on Home looks broken.

## Decision

**A question about what the platform holds for the person gets an answer in the model's own words.** The reading gains one more kind, `my_data`. A question about the software on the watchlist and its versions, about the person's workflows and their last runs, or about what needs them, is `my_data`. When code reaches that kind, it asks the model once more, with the question and a facts snapshot as JSON. The reply is a `question` answer: its text (600 characters at most) and `looked_at`, the sections it used (`watchlist`, `workflows`, `needs_you`).

**The facts are read when the question arrives, by the code the screens use.** platform-api builds them from the Software page's rows, the Workflows page's workflows and newest runs, and the counts Home shows under Needs you. The Software and Workflows facts are the team's, as those pages are. Needs you is the signed-in person's. A section that cannot be read, or would not fit the cap (100 software, 50 workflows), is left out.

## The guards

- **Read-only.** The lane has no tool and no write. The facts are a copy, and the reply changes nothing.
- **Facts only.** The model may use only the facts, and counts from them. If they do not hold the answer, it says so in one sentence.
- **No offers.** The reply may not say what the platform can or will do, or offer to set something up or act. Code checks the reply for such phrases, and for length.
- **Sources shown.** Code keeps only the sections that were really sent. The Portal shows them as "Looked at", linked to the screens.
- **A fixed fallback.** If the facts are missing, or the reply offers to act or runs long, the answer is the fixed text "I couldn't answer that from what I can see." with no sections.

## What stays fixed

Set-up cards, parts, can'ts, refusals, watchlist set-ups, "what can you do" and the chips keep their fixed text. A request that asks for a change stays a task even when it also asks a question, so no part of it is dropped. The approval gate, the safety checker and the word rule for skipped yes answers are unchanged.

## Not now

Questions about Jira tickets are not `my_data` in this phase. A search still becomes a set-up card. A read of live Jira for an answer needs its own decision.

## Considered options

- **Fixed text per question kind.** Safe, but each new question needs new code and text, and a count or a version lookup cannot be fixed text.
- **Let the model call tools.** It could answer anything, but it would need a read tool per source and a way to keep it from writing. The snapshot is smaller and cannot write.
- **Send the facts with the first call.** One call less, but the model would see the data on every request, including tasks.

## Consequences

- A typed request that is a question costs a second model call, so the platform's limit around the answer is 20 seconds, up from 10.
- The facts go to the AI model provider. They are names, versions and counts the team already keeps on its pages.
- The eval set gains five cases for the reading. The reply guards are covered by unit tests and a live check.
- The glossary gains "Question answer".

## Decision record

Accepted by the user on 8 Nov 2026: a read-only question lane, with the guards above.
