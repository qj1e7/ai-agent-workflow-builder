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

**A watch of "it" (16 Nov 2026).** The Portal also sends the one software the previous answer named (`previous.software`): a watchlist offer, a can't whose alternative is a watchlist offer, a question answer about exactly one software, or a remove answer for one name. When the typed text is only a watch verb and "it", such as "keep track of it", the answer is the offer to watch that software. The platform takes the software only after one of those four kinds of answer, or a free reply (below). The name is client input, so it must be a plausible name that is software and names no ticket and no yes, and the person must tap the offer, so nothing is written. With no software in the previous turn, the Planner still asks which software.

**A plural is never one software (17 Nov 2026).** "them", "'em", "those", "these", "both", "each", "all", "all of them" and "the two" can't mean one name. A message that only asks to watch them, such as "track them" or "keep all of them", asks which software, whatever the previous turn named. Beside a named software in one message, as in "add redis and kafka, track them", such a clause is never ticked as the watch of that one software. It comes back as a part the Planner didn't follow.

**After a free reply (17 Nov 2026).** A free reply, an answer, a can't or a clarifying question, carries the one software its request named (`software`). Code finds the reading's software in the request's own words and holds it to the same rules. It is also held to the check a watch typed in one turn passes: the request names no ticket, project, person or workflow. The name must be the only one the request gives, and at most 80 characters. The request names a second software when a plain name follows and, or, than, with, plus, then, against, besides, instead of, rather than, what about, as well as, vs, a comma, a semicolon, an ampersand, a slash or a plus sign. It also names one when a plain name is joined just before the name, or added with too, also or as well. Marks, quotes and articles may stand between. A plain name is never a common word: an auxiliary, a question word, a pronoun or a plain adverb, so "what's new in node js and should I upgrade?" names one software. "to", "over" and "not" join nothing, as too many one-name requests use them, so a guess they leave is still only a card they tap. "keep track of it" beside the name is the same watch, so it joins no second name. Then the reply carries none, so "keep track of it" after "is redis newer than kafka?" asks which software and drops neither. It never takes a name from the reply's text. The Portal sends it back as `previous.software`, and sends none once a Changed in n8n card came after the reply, as for the four answers above. The runtime takes it only when the previous request holds it word for word. So "keep track of it" after "tell me about node js" offers to watch node js, as "keep track of node js" would.

**A question about the newest version (17 Nov 2026).** A question that asks only for the newest version of one software gets the offer to watch it, or the answer about the watched software. Examples are "what's new in node js?", "what is the latest node js?", "latest version of redis", "any updates for langgraph" and "is terraform up to date?". It never reaches the free reply. Code checks the question's words itself. The model only names the software. Code finds that name in the request. When the model wrote a longer, official name, code takes only its leading word, when the request writes that word whole, as "node" for "Node.js", never "server" for "SQL Server", and never from a name longer than 80 characters. A maker's name that leads the official name, such as Apache, HashiCorp, Microsoft, Google, Amazon, AWS, Azure, Oracle, IBM, Red Hat or Eclipse, is not that leading word. Code takes the next word instead, as "kafka" for "Apache Kafka", and never "apache". It holds the name as a free reply's software is held. Around the name the request may hold only words that ask what is newest, plus question words, small words, pronouns, polite asks and the verbs of a question: tell, show, know, check, find, see, run and use. The words that ask what is newest are new, newer, newest, latest, recent, current, update, updates, up to date, out of date, outdated, behind and the release words. Each clause must hold the name or one of those words, or only say please. Any other word, such as "news", "team", a number or a second name, takes the usual path. So does a name glued to a sign, as "c" read from "c++".

These get no offer, and keep the answer they had:

- A request that orders a change or a use, as "update node", "can we upgrade redis?" or "use the latest node js".
- A request that names a system the platform doesn't reach, such as Outlook, Entra or GitLab, or a release source it doesn't read, such as npm, PyPI or Docker Hub. Each keeps its can't, with or without a release word. Helm is software as well as a source, so it keeps the offer.
- A request that holds a key, or names one of the person's workflows.
- A name that is one of the platform's own, such as the Planner or the watchlist, "news", or a word that asks what is newest or a question word, as "current" read from "is the version current?".
- A reading of a question about the person's workflows or what waits for them, a reading of a change to a workflow, a reading of a ticket search, and a reading that skips anyone's yes or attention.

A question about what was done, as "did we upgrade kafka?", gets the offer, because the version the team runs is what the watchlist knows. The word on the offer is the request's release word if it has one, as for a watch. Otherwise it is the first word that asks what is newest. When the watchlist holds the software under another spelling, with case, spaces, dots and hyphens aside, the answer names it as the watchlist does, so the question lane answers it as watched software. The check comes after the refusals, explain, a release source the platform doesn't read, removal and edit, so each of those answers first. The person still taps Watch it, so nothing is written.

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
