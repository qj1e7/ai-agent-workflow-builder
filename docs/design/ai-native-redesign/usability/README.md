# Click-through test of prototype version 4

This kit runs a short test of the redesigned prototype with people who have never seen it. Everything checked so far was a script or an AI reading the screens. Nobody has yet tried to use it cold. The test finds where a non-technical support Operator hesitates, misreads or gets stuck, while that is still cheap to change.

Files:
- `README.md`: this guide, for the facilitator;
- `tasks.md`: the task cards, one per scenario. Print them, or show them one at a time;
- `observation-form.md`: one sheet per participant, and the summary table.

## What it should answer

The test feeds these open design questions:

1. Do people notice Needs you on Home and act on it, or does Home feel busy (scenario B)?
2. Do people understand the set-up card's sentence, that it creates a Jira ticket, and that someone else must agree first (A)?
3. When the Planner says it can't do something, do people know what to do next, or feel stuck (D)?
4. Can people fix the Planner's guess without starting again (E)?
5. Can people tell a stop they can fix from one they must report (F)?
6. Do people find Pause, Change schedule and Delete, which sits inside More actions (H)?
7. Does an Approver understand what will change, and who asked, before saying yes (C)?

## Who and how many

- **Who.** 3 to 5 people who have never seen the app. CODESparks support staff are best, because they are the real users. If that isn't possible, use people outside our team who don't work in software. Our own five know the design too well to count.
- **Time.** About 35 minutes each.
- **Rooms and roles.** One facilitator. A second person taking notes helps a lot.

Arranging sessions with CODESparks staff goes through the sponsor, so the team lead asks.

## Setup

- **Device.** A laptop browser at least 1280 pixels wide, with the prototype link open. Open it fresh for each person, or press Start over in Test controls.
- **Test controls.** Only the facilitator uses the Test controls button at the bottom left. Tell the person it is a testing panel, not part of the app. Each task below says how to set it before handing over the card.
- **Recording.** Record the screen and voice only if the person agrees. Write P1, P2 and so on in the notes, never names.

## What to tell the person first

> Thanks for helping. We're testing a design for a new tool, not testing you. There are no wrong answers. If something is confusing, that's exactly what we need to know.
>
> Please think out loud as you go: what you're looking for, what you expect to happen, what surprises you.
>
> This is a mock-up. The data is made up and nothing reaches a real system. The text box understands simple wording only. If it doesn't understand you, that's the mock-up's limit, not yours. I may give you different words to try.
>
> I'll mostly stay quiet so I see how it works without help. If you're stuck for a while, I'll give you a hint.

## During each task

- **Hand over the card** and let the person read it. Start timing when they look up from the card.
- **Stay quiet.** Neutral prompts only: "What are you thinking?", "What do you expect that to do?"
- **Hints.** Give one only after about two minutes stuck, or when they ask twice. Then mark the task as assisted.
- **Words they type.** If the box doesn't understand, write down their exact words first. Then offer the backup wording on the card. Their own words are input for the real AI model's test set (plan section 7.5).
- **Stop the task** at success, or after about five minutes. Mark it failed if they didn't get there.
- **After each task,** ask the two rating questions and the task's follow-up questions in `tasks.md`.

## The tasks

Run them in this order. A comes first because it is the first visit. Bob's task C comes last, so the person switch happens once.

| Order | Scenario | Set Test controls to | Success looks like | Watch for |
|---|---|---|---|---|
| 1 | A. First visit | Act as Alice. Show: Day one | A weekly workflow is on, with a Jira project and a time chosen | Do they find the box straight away? Do they read the sentence? Do they notice it creates a Jira ticket, and that an Approver must agree each time? |
| 2 | G. Watch software | Act as Alice. Show: A normal week | Kubernetes is on the Software watchlist | Do they use the box, or hunt through the menu? Do they understand "Start from the newest"? |
| 3 | E. The Planner guessed wrong | Alice, a normal week, Start over | One set-up card shows project OPS and Monday, and nothing started again | Do they edit the card, or retype the request? Can they find the schedule? |
| 4 | D. Something it can't do | Alice, a normal week, Start over | They can say why it can't, and name a next step, such as Ask the team | Do they feel stuck? Do they trust the explanation? |
| 5 | B. What needs me today | Alice, a normal week, Start over | They retry the stopped Morning new-ticket check | Do they notice Needs you on Home? Do they understand "Jira didn't answer"? |
| 6 | F. A run stopped | Alice, a normal week, Start over | They retry the Jira stop, and report the Weekly closed-ticket summary to support | Can they tell which stop they can fix and which they must report? |
| 7 | H. Change, pause, remove | Alice, a normal week, Start over | Morning new-ticket check runs at 9:00 and is paused. Weekly closed-ticket summary is deleted | Do they find each action? Do they read the delete confirmation? |
| 8 | C. Approve a change | Act as Bob. Show: A normal week, Start over | They decide on the 3 upgrade tickets after reading them | Can they say what will change and who asked? Do they think the AI's summary is the check? |

## At the end

Ask:
1. What was most confusing?
2. What would you miss if it were taken away?
3. Would you let this run every week without watching it? Why, or why not?

## After all sessions

1. **Fill in the summary table** in `observation-form.md`.
2. **Decide what counts.** A problem counts as a finding when two or more people hit it, or when one person misreads something about safety. Examples: thinking a write happens without a yes, or thinking they approved something they didn't.
3. **Change the prototype for each finding.** Re-run the checks in `checks/`, and note the change in `decisions.tsv`.
4. **Add the words people typed** to the golden-set cases (plan section 7.5).
5. **Report honestly.** This is a small, early test. It shows where people struggle. It can't prove the design works for everyone.
