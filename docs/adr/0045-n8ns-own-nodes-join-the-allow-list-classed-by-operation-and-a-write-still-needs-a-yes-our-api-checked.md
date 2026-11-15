---
status: accepted
---

# n8n's own nodes join the allow list, classed by operation, and a write still needs a yes our API checked

**Accepted on 14 Nov 2026, as "reads and notices now".** The team lead chose: n8n's own nodes may read and post notices now, with credentials the platform owns. Writes to Jira and Confluence stay with our "Make the approved changes" block (option B). The `write` class starts empty and stays empty until the team lead names a system and E18 builds the write proxy (option C, designed below, deferred). No unproxied write (option A) and no licence (option D) for now. One condition comes with "now": a node type that also has write operations (Jira, GitHub, Slack) joins the list only when the platform's credential for it is a key the system scopes to reading or sending, and the credential sweep (section 2, E17) runs from the same release, because the checker cannot stop a member from running a draft by hand with another operation and their own key.

On 14 Nov 2026 the team lead said "I can create any workflows, as long as n8n is capable to do it", and chose: the Planner may use n8n's built-in nodes too; our checker puts Ask for a yes before every node that changes data; HTTP Request, Code and Webhook stay off. ADR 0027 had limited every n8n workflow to our node pack plus IF, Merge, No Op, Sticky Note and the three triggers. This widens the allow list and so touches the approval gate and the safety checker, which `AGENTS.md` says needs an ADR.

The decision, in one paragraph: n8n's own nodes may build a workflow, but each node type and each of its operations is classed `read`, `notice`, `write` or `off` in a data file our checker reads, with unknown meaning `off`. Reads and notices run with credentials the platform owns. A write to a system we support (Jira today, Confluence next) is still made only by our "Make the approved changes" node through the write gateway. A built-in write node is allowed only when its credential can be pointed at our write proxy, so the real key stays in Key Vault and the proxy checks our own records at the moment of writing, as ADR 0026 requires. Where a node's credential has no base URL we can point at the proxy, the node's write operations are `off`. This keeps the guarantee as strong as today for every system we support, and nearly as strong for the rest, with two named gaps the team lead must accept or close with a licence.

## 1. Which nodes and operations, and how each is classed

**The classes.**

| Class | Meaning | Runs with | Needs a yes |
|---|---|---|---|
| `read` | Reads from a system and changes nothing there | A platform credential | No |
| `notice` | Sends a message to a place fixed in the workflow, with content from the run's own data (the Tell rule, ADR 0026) | A platform credential | No |
| `write` | Changes data in a system of record | A platform credential that points at our write proxy, so the write cannot happen without a token our API issued after a yes | Yes, always |
| `off` | Not allowed, or not yet classed | Nothing | Cannot be published or run |

**The data.** `platform-api/src/platform_api/orchestration/node_classes.json` holds one entry per `(node type, typeVersion, resource, operation)` with its class, the parameter that names the target (`project`, `channel`, `to`), a `says` template for the approval card and the block tag ("Reads Jira", "Posts in Slack", "Closes a GitLab issue"), `approvers_min` (1, or 2 for an operation that changes someone's access), and for a `write` the proxy's field map (which request fields the Approver's Details show and the proxy compares). An entry has no default: a type or an operation that is not in the file is `off`. A node whose `operation` is an expression is `off`, because its class could change at run time.

**The first allow list beyond ADR 0027's.** Jira (read operations only, since Jira writes stay ours), GitHub (read operations), Microsoft Teams (send a channel message: `notice`), Microsoft Outlook and Gmail (send: `notice`; everything else `off`), Slack (post a message: `notice`), and P7 Q10's data nodes (Filter, Switch, Edit Fields, Limit, Aggregate, Split Out, Remove Duplicates, Summarize, Rename Keys, Date & Time, Compare Datasets, Loop Over Items, XML, Markdown, Execution Data, Stop and Error) as `read`-class shaping of items. HTTP Request, Code, Webhook, Wait, Execute Workflow, Respond to Webhook, Sort and Item Lists stay `off`, as do n8n's AI agent nodes (ADR 0023). The `write` class starts empty. A system the sponsor wants written through a built-in node (GitLab, for example) is added by a PR that classes its operations, maps its fields and proves the proxy with it.

**How it stays true when the pin moves.** A CI check reads `/types/nodes.json` from the pinned image, lists every operation of every type that `NODES_INCLUDE` names, and fails when one is missing from `node_classes.json` or when a classed `typeVersion` no longer exists. Moving the pin therefore means re-classing in the same PR. `NODES_INCLUDE` is generated from the file, so the list n8n loads and the list the checker grades cannot drift apart.

## 2. Keeping "no write without a yes the platform checked"

ADR 0026 rests on two facts: n8n holds no write key, and the write gateway checks our own records at the moment of writing. A built-in write node breaks both unless we design around it: it writes with an n8n credential, at the moment n8n reaches it, whatever our records say. These are the options.

| Option | How it works | What survives |
|---|---|---|
| A. Grade-time only | The checker inserts Ask for a yes before every write node; the sweep re-grades every published version; n8n runs whatever is published, with a static credential. | Nothing at run time. A yes removed in n8n writes until the sweep sees it (up to 60 s), and a draft run by hand writes with no check at all. ADR 0026's "safety can no longer depend on the route" is given up. |
| B. Our node stays the only writer | Built-in nodes read and notify; every change to data goes through "Make the approved changes" with a connector of ours. | Everything, exactly as today. A new system means a connector in our code. |
| C. Lent credentials through a write proxy | A built-in write node's credential belongs to the platform and points at our write proxy, not at the system; its secret field is an expression that reads a run token our Ask for a yes node emits on its Yes exit. The proxy checks the token against our records (approved, digest, not expired, not done, target and operation as approved, count), then forwards with the real key from Key Vault. | The key never sits in n8n, and the check is at the moment of writing. It works only for credential types that carry a base URL (Jira Server, GitLab, generic OAuth2 or Header Auth) and for nodes whose request can be read by the proxy. The Approver's digest covers the target, the operation, the count and the mapped fields, not every field. |
| D. Paid n8n with credential and node policies | n8n 2.42.6's API lists credential-type policies and node-type policies per project. If they work on our edition, staff cannot create credentials or use write nodes at all, and C's remaining gap closes. | To be proven on the free edition (P8). If licensed only, it is a sponsor purchase. |

**Recommendation: B for every system we support, C for the rest, D if it is free, and never A.**

- **Who owns the credentials.** Only the platform creates credentials, in its own n8n project, from Key Vault, through the public API; each is tagged with the system and class it serves. Staff with n8n access cannot select them: the free edition cannot share a credential across projects (P6 Q3), so a credential in the platform's project is not offered in a member's editor. When "Open in n8n" transfers a workflow to a person, the platform also transfers the credentials that workflow's `read` and `notice` nodes name, and takes them back with it. A `write` node's proxy credential is transferred too, and is harmless in any other workflow: without a token from a yes, the proxy answers 401.
- **A write only after a yes our API woke, proved at run time.** Ask for a yes's Yes exit carries `wab.token`, issued by our API inside the wake, scoped to the run, the request and the approved actions, and dead after the acting deadline. The proxy credential's secret is `={{ $json.wab.token }}`. The checker also requires that a `write` node's input is the Yes exit of an Ask for a yes, directly, so Ask can resolve the write node's parameters against the same items and build the proposal the Approver sees. At run time, no token means no write, whatever the route in n8n looks like. A draft run by hand reaches the proxy with no yes and is refused. A test run never gets a token, because a test run stops at the yes (ADR 0044).
- **A yes removed in n8n before the sweep sees it.** Nothing is written in that window, because the write node has no token to present. The sweep then grades the version `Writes refused` and the chat gets the "Changed in n8n" card, as ADR 0027 already says. The window matters only under option A.
- **Our own node stays the only writer for Jira,** and for Confluence once its connector exists, because there the gateway checks the full digest of every field, and because `jira.create_ticket`'s subject key and the practice-Jira rule (ADR 0041) live in our code. A built-in write node is for systems we have no connector for, and it joins the `write` class only when its proxy field map is written and tested.

**What is weaker than today.** Two things, both only when a `write`-class built-in node exists, which it does not yet:

1. **The digest.** For a built-in write the Approver's digest covers the target, the operation, the count and the mapped fields. n8n builds the request after the yes from expressions, so a field outside the map could differ from what the Approver read. For our own writes the digest covers every field.
2. **Staff keys.** The free edition lets any member create a credential (P6 Q6). With a write-capable node type on the allow list, a member could make a credential to the real system and point a draft at it. The proxy cannot see that write. The guard is the credential sweep: every 60 s, and on every "Open in n8n", the platform lists all credentials as the owner, deletes any it did not create, and marks the holder's workflow `Needs a fix: a key was added in n8n`. That leaves a window of up to a minute for a person who already holds n8n access. Option D closes it if n8n's policies work on the free edition; P8 finds out. This gap exists as soon as a node type with write operations (Jira, GitHub, Slack) is on the list, even with only its read or notice operations classed: n8n's allow list is by type, not by operation, so a member can set another operation in a draft and run it by hand with their own key, and the checker never sees that run. Two things hold it to the window above: the platform's own credential for such a type is a key the system scopes to reading or sending (an Atlassian scoped token, a fine-grained GitHub token, a Slack bot token with `chat:write` only), so the platform's key can never write; and the credential sweep removes a member's key within a minute. The remaining risk is a member with n8n access writing with their own key inside that minute, which is that person's own access to the system, not the platform's.

If the team lead wants a built-in write node with a fixed base URL (Slack's update, Google Sheets' write, Notion), there is no option that keeps the guarantee: it is option A. The ADR records that as a decision the team lead takes knowingly, per system, in a one-line amendment here, never as a default.

## 3. What the Planner proposes and the person sees

- **Blocks.** A built-in node is a block on the run line and the canvas with its n8n name as the label the Planner gives it ("Read tickets", "Post in Slack"), the badge `n8n block` where ours say `Our block`, and the tag from its class: `Reads Jira`, `Posts in Slack`, `Writes after a yes`, `Shapes the data` for data nodes. The sketch's inspector line for an n8n block reads `n8n's own block. {says}. {Reads only. | Posts to a channel fixed here. | Writes only after a yes, through our platform.}`
- **The set-up card** shows a built-in block as a ticked row like any other, and the build panel's status lines do not change. The footnote becomes `Our blocks and n8n's safe ones. Every change to data waits for a yes. The builder saves a draft. It can't publish by itself.`
- **The approval card for a built-in write.** Ask for a yes resolves the write node's parameters against its items and the class entry's `says` template, so the card reads as ours do: `Where`: the system and target (`GitLab, project ncs/platform`); `Summary`: `{says}` with the count (`Close 2 issues`); `Details`: the mapped fields as a table (`Issue`, `Title`, `Comment`), and one line `Made by n8n's GitLab block through our platform, after your yes.` The Approver sees the fields the proxy will enforce, and only those.
- **Capabilities.** The registry gains one entry per classed system and class ("read GitLab", "post in Slack"), so the Planner's "can't" answers and the set-up card's crossed rows stay honest (principle 5).

## 4. The rules that still hold

- **Two Approvers.** `approvers_min` in the class entry raises a write's steps to two for any operation that changes someone's access, and the model may ask for more, never fewer (ADR 0023). The proxy refuses a token whose request had fewer steps than the class demands.
- **Self-approval.** The parties are unchanged: the person who started the run, the publisher of the version, the holder for a manual run, the retrier, the Portal actor and the owner. A built-in write changes none of that, because the token is issued by `decide()`, which already refuses `own_work`.
- **The Tell rule.** A `notice` node needs no yes when its place is a literal in the workflow (the checker refuses an expression in `channel`, `to` or `chatId`), its content is built from the run's own items, and the registry entry says what it does. A message that asks a question, or carries a change to data, is a `write` (ADR 0023's Teams questions stay writes).

## 5. What changes in ADR 0026, ADR 0027 and AGENTS.md

- **ADR 0026** gains, under its acceptance: "A built-in n8n node may write only through the platform's write proxy, with a token our API issues after the yes and checks at the moment of writing. The Approver's digest for such a write covers the target, the operation, the count and the mapped fields." It also gains the credential sweep as a consequence.
- **ADR 0027** changes its allow list from a fixed list to "our node pack, n8n's triggers and flow nodes, and every n8n node and operation classed in `node_classes.json`"; its consequence "Each of n8n's other nodes is a decision" becomes "each is a row in the class file, with unknown meaning off"; and "n8n's data nodes come first" is done.
- **AGENTS.md** changes two lines with this acceptance (applied 14 Nov 2026):
  - "n8n holds no write key. The write gateway checks every approval itself at the moment of writing (ADR 0026)." becomes "n8n holds no write key. A write to Jira or Confluence is made only by our own node through the write gateway, which checks every approval against our records at the moment of writing (ADR 0026). A write by one of n8n's own nodes is not allowed until ADR 0045's write proxy exists for that system."
  - A new line: "n8n's own nodes may only read, or post a notice under the Tell rule. A node or an operation runs only when `node_classes.json` classes it; unknown means off. Only the platform creates credentials in n8n, scoped to reading or sending (ADR 0045)."

## Considered options

The four options in section 2. Two more were put aside:

- **Allow HTTP Request with a platform-only credential to our proxy.** It would make every system reachable through one node. But HTTP Request can also be pointed at any address with no credential, and P6 Q5 showed that is the leak the allow list exists to close.
- **Let n8n's own Jira node make the writes, and move the gateway's check into a proxy for Jira too.** One writer fewer. But our Jira connector already carries the subject key, the practice-Jira rule and the full digest, and the n8n Jira Cloud credential has no base URL, so the proxy could not sit in front of it.

## Consequences

- **P8, a short spike before the first `write`-class node:** credential fields take an expression at execute time on 2.42.6; credential-type and node-type policies on the free edition; the owner's credential transfer with a workflow transfer; what a member's editor offers from the platform's project; the proxy in front of a Jira Server and a GitLab credential, with a wrong, expired and replayed token.
- **The write proxy** is new code in platform-api (`orchestration/write_proxy.py`): one route per classed system, keyed by the token, with the field map. It logs each write with the approvers as the gateway does.
- **The credential sweep** joins the versions sweep. The daily self-test gains a credential the platform did not create, which must be gone within a minute.
- **The checker** gains: unknown operation is `off`; operation must be a literal; a `write` node's input is Ask's Yes exit; a `notice` node's place is a literal; `approvers_min` from the class.
- **The pack smoke** asserts n8n loads exactly the types `node_classes.json` names plus ours, and that every operation of each is classed.
- **ENGINE-PLAN** section 6 replaces E11 and E16 with the PRs that build this, drops the cert reminder's parser (E12 keeps only the general Confluence reader) and E14.
- **What does not change.** Runs, the wait in n8n, the sweep, Undo, the versions, the Tell flow, the n8n access flag and the chat-first sketch's screens and words. The only visible additions are the `n8n block` badge, its tags, and the one extra line on the approval card.

## Amended on 15 Nov 2026, as E16 and E17 were built

The team lead took these decisions on what building E16 and E17 found. Each one keeps a guarantee
this ADR gives, or makes it stronger.

1. **No platform key for Teams, Outlook or Gmail.** Their blocks stay classed, so a workflow that
   uses one grades `Needs a fix: it has no key`. n8n 2.42.6's own code shows why. Its Teams block
   posts to a channel only with a person's own sign-in ("app-only Graph supports only migration
   import"), which the platform cannot hold. Its Gmail block asks Google for `gmail.modify` and
   `mail.google.com` scopes, so a key that can only send does not work with it. It rewrites an
   Outlook app key each time it gets a token, so the sweep could not tell a key changed in n8n
   from one n8n refreshed. Teams notices go through our own Tell, under the Tell rule, so nothing
   is lost. The registry says so, and claims none of these blocks works (principle 5). The three
   types are still loaded, since n8n's allow list is by type: a member can run one only with a
   key of their own, in their own space, and the sweep removes that key within a minute.
2. **Only classic GitHub tokens, with read scopes or none.** GitHub does not say what a
   fine-grained token or an app may do, so the platform refuses one.
3. **A platform key never leaves the platform's project.** Section 2 said "Open in n8n" lends a
   workflow's keys to its holder. Building it showed a holder could then edit a lent key in their
   own space, point it at their own server, and read its secret. So a workflow that names a key
   opens in n8n without it. The holder can edit the blocks, and cannot run them with the key while
   they hold the workflow, because n8n lets a member's workflow use only the keys in the member's
   own space. On every take-back path (`take_back`, `release`, `back_in` and the recovery of a
   stranded move) the platform first runs the credential sweep, then puts its key back on each
   block for a system by the block's type, and takes every other key off. A block set to do what
   its class turns off, such as a Slack delete, gets no key, so a test run, which runs the draft
   in the platform's project, cannot run it with the platform's key. n8n's Community edition
   keeps a reference to a key the saver cannot use (spike P8), so the put-back is usually a check
   that changes nothing, and it covers the case where a reference was changed or dropped.
4. **A key's record is never moved on from n8n.** The record holds what n8n answered the
   platform's own create: the id, the type, and the times n8n made and last changed it. A key
   that differs from that record in any way, or sits outside the platform's project, is deleted
   and made anew from Key Vault. A new secret also makes the key anew. A key is never changed or
   moved in place.
5. **Every key is checked against what reading or posting needs, so anything unknown is a
   refusal.** Jira lists every permission it has; the account must hold none but browsing
   projects and seeing workflows, development links, voters, watchers and users. A Slack bot may
   hold `chat:write` and the scopes that read channel and people lists. `chat:write` also lets the
   bot edit or delete its own messages; the team lead accepts that, and it is recorded here.
6. **The owner bypass, and the rule it sets.** n8n lets a workflow in the owner's personal project
   use every key there is, a member's included. On the free edition n8n also lets a member
   publish a version naming a platform key they can't use (spike P8, Q12); it won't run it in
   their space, but it would there. So no workflow in the platform's project is ever
   live with a version that has a finding n8n would run anyway (`runs_anyway`), and no draft with
   one is ever run. Two places hold that rule. Every move into the platform's project, a
   take-back or a set-up, first takes off whatever n8n has published, takes off again whatever
   was published since just before the transfer, and again the moment the workflow lands, with no
   wait on its triggers. Then, with its holder or maker no longer able to change it, the platform
   puts the keys back on the draft, and only then checks. The window left is n8n's own transfer:
   a version published in the instant between the platform's last look and the transfer, which
   n8n carries live until the platform takes it off as it lands, before anything else. The version that was live, or for a
   take-back the one on record when nothing was, goes back on only if it passes. Otherwise it
   stays off, and the workflow is marked `Needs a fix`; a set-up sends it back to its maker. A
   version a member published that the platform puts back on stays the member's publish. A
   set-up whose move stopped part way puts nothing back on unless n8n shows the workflow back in
   its maker's own space. A version turned on, resumed or restored is checked again, as n8n holds
   it, just before it goes live, since the keys the platform holds may have changed since its
   grade. The
   sweep, every minute, checks every published workflow in the platform's project, whether a use
   case names it or not, takes off each that breaks the rule, and marks the use case that names
   it. Nothing is deleted. A version n8n does not show counts as one that breaks it. Open in n8n
   sweeps keys alone, since it holds the workflow's row and a mark would wait on it. The sweep
   takes off before it marks, and a mark waits at most five seconds on any row, so a lock cycle
   fails in place of stopping the sweep. The marks come from state, not from what the process
   remembers: each sweep marks every workflow the records say is on and n8n has off in the
   platform's project, and clears that mark once it is live again. One paused, a draft, deleted,
   held or on its way back is off on purpose and left alone. So a mark lost to a lock or a restart
   is made at the next sweep. A turn-on that lands between the sweep's look and its mark can be
   marked for one sweep, until the next look sees it live. A key Open in n8n removed is still
   remembered in the process until the next sweep marks the holder's workflows; a restart in
   that minute loses only that mark, as the key is already gone.
7. **A test run posts nothing.** A layout pins the output of each notice block. n8n uses pinned
   output only in a run by hand, which is what a test run is, and ignores it in every other run. A
   test run of a draft whose notice block has no pinned output does not start.
8. **Every run is recorded.** A workflow with any of n8n's own blocks for a system needs one of
   our blocks that calls the platform before the first such block, on every way from a trigger.
   That call links the run, so it is recorded and shown, and checks the version first, so a
   version that fails the check stops before n8n reads or posts. Without it the workflow grades
   `Needs a fix: Add one of our steps first, so each run is recorded.`
9. **n8n blocks are set up in n8n, not from the chat.** The Planner does not lay them out yet; the
   layout code can, and the registry says so.
10. **A take-back never lets go of a draft whose keys are not put right.** When n8n does not take
    the keys back on, the workflow stays held and marked `Needs a fix`, and the platform tries
    again each minute until it does.
11. **Keys are asked about again each day, and made one at a time.** Once a day the platform asks
    each system again what its key may do. A key that can now do more is taken out of n8n, and the
    sweep takes off every workflow that names it. A system that does not answer leaves the key in
    place until it does. One sweep looks at the keys at a time, so none deletes a key another is
    still making. platform-api runs as one replica, so a lock in the process is enough. The daily
    self-test's planted key is on record only once n8n takes it, so a plant n8n refuses is tried
    again at the next sweep, and the health line says the plant failed, never that the sweep
    missed a key. A key's id is at most 16 characters, which is all n8n takes (spike P8, Q13).
12. **n8n notice text is literal in this release.** The Tell rule now also covers what a notice
    says. Every word of an n8n notice is written out in the block, never an expression, so the
    checker reads all of it before anything runs; a notice that says what a run read goes through
    our Tell, which the platform controls. Slack's blocks are decoded from their JSON first, and
    blocks that don't decode are refused. The words are matched in NFKC and case-folded, and none
    may call out a whole channel or a user group: no `<!channel>`, `<!here>`, `<!everyone>`,
    `<!subteam^…>`, `@channel`, `@here` or `@everyone`. Slack's `link_names` stays off, since it would turn a written @channel into a
    call to everyone. The class file names each notice row's text, and a notice row without it is
    refused. A block that breaks this runs anyway, so it is never live.
13. **A test run runs only the draft the platform checked.** When a test run is asked for, the
    platform checks the draft and keeps its version id with the run. The start compares that id
    with the draft n8n holds and does not start one that changed. We chose this over sending the
    checked document in the run body (`workflowData`): spike P7 proved the body without it on
    n8n 2.42.6, and the version id is n8n's own lock, the one every platform write already uses.
    Whether n8n runs a `workflowData` it is sent, and with which keys, is not proven. Whether
    someone holds the workflow is read in the same transaction that records the run, which also
    holds the workflow's lock, so an Open in n8n can't cross it.
14. **A test run reads with the platform's key.** A test run runs the draft by hand in the
    platform's project, so its Jira and GitHub blocks read with the platform's keys. What those
    keys can see is what any Operator can read through a test run. Give the Jira key an account
    that sees only the projects Operators may see, and the GitHub key no more than the
    repositories they need. `infra/README.md` says so where the keys are set.

`attach_keys` may change one parameter of a block it puts a key on: the one that picks which
credential type the block asks for, such as Jira Cloud or Data Center. That changes how the block
signs in, not what it does, which the class file already checked, so it is not a finding.

Also found while building: n8n adds a "Custom API Call" choice to every node with a key, which
sends any request with that key, and makes a human-in-the-loop AI tool of the Slack, Teams,
Outlook and Gmail nodes. The class file turns all of them off, and the pin check names each.
