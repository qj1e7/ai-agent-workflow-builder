---
status: proposed
---

# Sign in with OpenID Connect; Entra ID in Azure

People sign in to the Portal with OpenID Connect, and platform-api trusts only the access token that the identity provider signs. In Azure the identity provider is Entra ID. Until now the only sign-in was the dev stub, where a person picks a name and the Portal sends `X-Dev-User`. platform-api refuses that mode on any host but localhost, so nothing could run on a shared deployment. ADR 0009 already said that Approvers need a real sign-in before any shared deployment.

The Portal signs in with the Authorization Code flow and PKCE, through `oidc-client-ts`, a maintained library that speaks plain OpenID Connect. It sends the access token as `Authorization: Bearer` on every API request, the event stream included. platform-api checks each token itself, behind the `Authenticator` port that the dev stub already uses: the signature against the provider's published keys (RS256 or ES256 only), the issuer, the audience, and the expiry and not-before times with 60 seconds of leeway. `AUTH_MODE=oidc` turns this on. platform-api refuses to start when a setting is missing or the issuer is not https.

## Why OpenID Connect and not an Entra-only library

ADR 0004 keeps a move to AWS open. Microsoft's own libraries (MSAL in the browser, Microsoft.Identity.Web on a server) work only with Entra. Entra, Amazon Cognito and Keycloak all issue standard OpenID Connect tokens, so a generic client and a generic token check work with each of them. Only configuration and the setup guide name Entra. The flow is the one MSAL uses, so we give up nothing on Entra.

## How roles map

Entra app roles named `Operator` and `Approver` arrive in the access token's `roles` claim. platform-api maps those two exact values to its two roles and ignores any other value. A person whose token carries neither role can read runs but gets 403 on every route that needs a role. Approving still needs the Approver role, as before. The person's id is the token's `oid` claim, or `sub` when there is no `oid`. Both stay the same for the life of the account, which matters because the approval rules compare ids. The display name is `name`, then `preferred_username`. The Portal learns who is signed in from a new `GET /api/v1/me`, so the Portal never reads a token and the server's mapping is the only one.

On AWS, Cognito puts groups in `cognito:groups`, so a move there needs a pre-token-generation trigger that copies them into `roles`. That is configuration, not a code change.

## Token lifetime and refresh

Entra issues access tokens that last 60 to 90 minutes. The Portal asks for `offline_access` and renews the access token with the refresh token about a minute before it expires. The Portal's content security policy rules out the hidden iframe and the popup that other renewal methods need. Entra limits refresh tokens for single-page apps to 24 hours. After that the person signs in again, usually without typing anything while their Entra session lasts. If a renewal fails, the Portal says the sign-in has ended and offers to sign in again.

platform-api keeps no session. It checks every request, and it caches the provider's keys for an hour, then refreshes them in the background while it keeps answering from the cached keys. When a token names a key it does not know, it fetches the keys again, at most once every 30 seconds, so tokens with made-up key ids cost the provider at most one request in that time. If the keys cannot be fetched, it answers 503, not 401, so a short outage at the provider does not sign people out. It stops trusting cached keys that are more than a day old.

A role removed in Entra takes effect when the person's current access token expires, so after at most about 90 minutes. An open event stream is checked when it connects, and again on each reconnect.

## What stays the same

- An Approver can never approve their own work, and the access review's two steps keep their order with a different person for each. These rules live in the approval gate and only see the `Principal` the port returns, so they do not change.
- No write action runs without approval. Machine credentials (`X-Step-Key` from n8n, the agent callback token, the Agent API key) do not change.
- Dev mode is unchanged. It still needs a localhost `PUBLIC_BASE_URL`, and `X-Dev-User` is ignored in oidc mode.

## The human steps

Someone with rights in the Entra tenant registers two apps, one for platform-api and one for the Portal, creates the app roles, assigns people, and gives the deploy the resulting values. [docs/auth/entra-setup.md](../auth/entra-setup.md) lists the steps and the Terraform variables. No code reads a tenant id.

## Considered options

- **Entra-only libraries (MSAL, Microsoft.Identity.Web).** They are less code on Entra, but a move to AWS would mean rewriting sign-in on both sides.
- **Sign-in at the platform edge** (Container Apps authentication, or an oauth2-proxy in front). platform-api would trust a header that the edge sets. That is safe only if no other path reaches the API, and it ties us to one platform's header format.
- **A backend for the frontend** that keeps tokens on the server behind a session cookie. The browser would hold no token, but we would add a session store, cookie and CSRF handling, and nginx cannot run the flow.

## Consequences

- The Portal must be served over https, or on localhost, in oidc mode, because PKCE needs the browser's secure-context crypto. A DevNet deployment on plain http needs TLS before it can use real sign-in. Dev mode still works on plain http.
- The contract declares a second security scheme, `OidcBearer`, next to `DevUser` on the same routes, a 503 on every signed-in route, and the new `/api/v1/me`.
- Tests run against a mock identity provider in Docker (`navikt/mock-oauth2-server`, pinned by digest), so no real tenant is needed. Its http issuer is allowed only through `OIDC_TEST_ONLY_HTTP_ISSUER`, which must equal the issuer and is refused unless `PUBLIC_BASE_URL` is on localhost.
- New dependencies: PyJWT with `cryptography` in platform-api, and `oidc-client-ts` in the Portal.
- platform-api does not check what kind of token it got. The setup keeps the two kinds it must refuse away from its audience: with two app registrations an ID token's audience is the Portal, and with **Assignment required** an app that signs in as itself gets no token for platform-api. A deployment that cannot promise both should add a check for the API's delegated scope in the token.
- Other people's names: the API stores user ids, and only the signed-in person's own name comes from `/api/v1/me`. With Entra ids, the Portal cannot yet name the person who started or approved a run outside the activity view, which records names. A follow-up can carry the name next to each stored id.
