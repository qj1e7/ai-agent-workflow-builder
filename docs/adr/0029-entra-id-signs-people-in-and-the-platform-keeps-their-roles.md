---
status: proposed
---

# Entra ID signs people in, and the platform keeps their roles

ADR 0018 takes each person's roles from the `roles` claim in their Entra token. Someone with rights in the Entra tenant assigns the app roles Operator and Approver, and platform-api reads them on every request. The prototype instead changes roles in the Portal, under Settings, People and roles. Its rules come from the sponsor's concern that nobody approves their own work:

- An Operator can make someone an Operator, or stop them being one, at once, with Undo. Nobody can remove their own Operator role.
- Making someone an Approver needs a second person. An Operator asks, and an Approver who is neither the asker nor the new Approver confirms.
- Someone named on a workflow keeps the Approver role until another person is named there.
- At least two people are Approvers, so nobody has to approve their own work.
- Every change is recorded with who made it, and who confirmed it.

Entra can't hold these rules. Only the Entra app's owner or an Entra admin can assign an app role. Entra has no step where a second person confirms. And a role removed in Entra stays in a token for up to about 90 minutes. Who holds the Approver role decides who may approve, so this changes the approval gate, and `AGENTS.md` requires an ADR. The [design note](../design/portal-routines.md) already says that roles changed in the app need their own ADR.

So Entra ID only signs people in, and platform-api keeps each person and their roles in PostgreSQL:

- **A person** has our own id, their Entra object id (`oid`), their email, a display name, an Operator flag and an Approver flag. A person can hold both roles. Every other record stores our id. The `Authenticator` port maps the token to that id, so `Principal.user_id` is always our id. The own-work check therefore compares like with like.
- **People are added in the Portal.** An Operator adds a person by their NCS email. On that person's first sign-in, platform-api compares the token's user name with the email, ignoring case. The user name is `preferred_username` in Entra's v2 tokens and `upn` in v1 tokens. If they match, platform-api stores the `oid`, and from then on it matches only on `oid`, which never changes for the life of the account. Microsoft warns that the user name can change, so it is used once, to bind a record an Operator created, and never to decide access after that. ADR 0018's issuer check already accepts tokens from one tenant only.
- **Someone who signs in but is not on the list** sees "Ask an Operator to add you". `GET /api/v1/me` answers so the Portal can say that, and every other route answers 403. Under ADR 0018, a person with no role could still read runs.
- **Roles are read from our table on every request.** platform-api ignores the `roles` claim. A role removed in the Portal takes effect on the person's next request. An open event stream checks the person again every minute, and closes when they are no longer on the list.
- **Role changes run one at a time.** Each change locks the People rows in its transaction, then checks the rules. So two changes made at the same moment can't leave fewer than two Approvers, or no Operator at all. At least one person must stay an Operator.
- **The rules above run in platform-api.** The Portal only shows them. A pending Approver is a confirmation request, built on the same mechanism as a new AI model address (ADR 0022). ADR 0030 makes that mechanism shared.
- **Every role change goes into the settings history,** with who asked, who confirmed and when, as ADR 0022 already records changes to the AI model. The activity log stays per run, and a role change belongs to no run.

The approval rules in `orchestration/approvals.py` see only the `Principal`, so they do not change. Sign-in does not change either. The flow, the token check, refresh and the mock identity provider stay as ADR 0018 describes.

## Considered options

- **Keep Entra app roles (ADR 0018).** Microsoft recommends app roles, and they need no table of ours. But an Operator could not change who may approve. NCS IT, or one technical person who owns the app, would make every change. The second-person rule and the "named on a workflow" rule would have nowhere to run, and a removed Approver could still approve for up to 90 minutes.
- **Entra groups.** The same admin problem. Assigning groups to an app also needs Entra ID P1 or P2.
- **Entra app roles, shown read-only in the Portal.** One place holds roles. But People and roles becomes a page that tells an Operator to ask IT, which is what the sponsor wants to avoid.
- **Our own passwords.** People would get no single sign-on, no multi-factor sign-in, and no automatic end when they leave NCS.

## Consequences

- **ADR 0018's "How roles map" no longer holds.** The rest of ADR 0018 stands. [`docs/auth/entra-setup.md`](../auth/entra-setup.md) drops the steps that create and assign app roles.
- **NCS should set Assignment required with one group.** Then only CODESparks staff can sign in at all, and a user name that is later given to someone else can't claim a record nobody has used yet. Assigning a group needs Entra ID P1 or P2, which NCS's tenant is likely to have. IT assigns the group once, and Operators still manage roles. The student tenant for the demo relies on the one-tenant issuer check and the one-time match.
- **We secure the role data ourselves.** Microsoft calls an app's own role store the most complex option, and the app owns its security. The role routes are Operator-only. An Approver grant always waits for a second person. The DAST scan covers the new routes, as it covers the decision route today.
- **An empty People list needs its first people.** ADR 0030 covers that.
- **One person across systems.** Each card action from Teams carries the person's Entra object id, and n8n users match by email (ADR 0027). Both resolve to the same person record.
- **Names come back to the Portal.** ADR 0018 could not name the person who started or approved a run, because the API stored only ids. Our table holds names.
- **Dev mode keeps today's dev users as seeded people.** alice is an Operator and an Approver, bob is an Approver, and carol is an Operator, as in `platform-api/src/platform_api/auth.py`. Tests that put roles in mock tokens seed people instead.
- **A person who leaves NCS** can no longer sign in once Entra disables the account. Their record stays, so past runs keep their name. An Operator removes their roles. If they are named on a workflow, an Operator names someone else first.
- **This narrows ADR 0024.** ADR 0024 skips a named person who has lost the Approver role. Under this ADR, a named person keeps the role until someone else is named, so a request never goes to a person without it. The "named on a workflow" rule takes effect when ADR 0024's named Approvers are built.
- **If this ADR is accepted,** the glossary's Operator and Approver entries gain the duties above.
