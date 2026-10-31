# Set up Entra ID sign-in

This guide is for the person who holds admin rights in the Entra tenant. When you finish, people sign in to the Portal with their work account. Entra only signs people in. Who is an Operator and who is an Approver is kept in the platform's own People list, which Operators manage in the Portal, and the first deploy names the first people through `FIRST_OPERATOR` and `FIRST_APPROVERS`. [ADR 0018](../adr/0018-sign-in-with-openid-connect.md) explains the sign-in and [ADR 0029](../adr/0029-entra-id-signs-people-in-and-the-platform-keeps-their-roles.md) and [ADR 0030](../adr/0030-operators-look-after-setup-and-the-first-deploy-names-the-first-people.md) explain the roles. Both role ADRs are still proposed.

You register two apps. One is for platform-api, which the tokens are for. One is for the Portal, which signs people in. Keep them separate: platform-api does not check the kind of token it gets, and two registrations keep the Portal's ID token from ever passing as an access token for platform-api. In this guide the Portal's https address is `https://<portal-host>`. When you deploy to Azure, Azure picks that address as the first deploy creates the environment, and the deploy prints it. So for a first Azure deploy, register both apps, leave out the Portal's redirect URIs, and add them once the deploy has printed the address. [infra/README.md](../../infra/README.md#one-time-human-steps-before-the-first-deploy) lists that order.

## Register the app for platform-api

1. In the Entra admin center, open **App registrations** and select **New registration**.
2. Name it, for example `Workflow platform API`. Select **Accounts in this organizational directory only**. Leave the redirect URI empty. Select **Register**.
3. Copy the **Application (client) ID** and the **Directory (tenant) ID** from the overview page.
4. Open **Manifest**. Set `requestedAccessTokenVersion` (under `api`) to `2`, then save. If you skip this step, tokens carry the old issuer `https://sts.windows.net/<tenant-id>/` and platform-api refuses every one of them.
5. Open **Expose an API**. Set the **Application ID URI** to the suggested `api://<api-client-id>`. Add a scope named `access_as_user`, with **Admins and users** able to consent, and save it.

## Limit who can sign in

platform-api adds nobody to the People list by itself: a person who signs in but is not on the list sees "Ask an Operator to add you", and an Operator adds them by their work email. Still, limit who can get a token at all, so a user name that is later given to someone else can never claim a record nobody has used yet.

1. Open **Enterprise applications** and select the platform-api app.
2. In **Properties**, set **Assignment required** to **Yes**.
3. In **Users and groups**, assign one group that holds the CODESparks staff. Assigning a group needs Entra ID P1 or P2. Without it, assign each person.

Nothing in Entra says who is an Operator or an Approver. A role change in the Portal takes effect on the person's next request.

One trust assumption remains. An Operator adds a person by their work email, and platform-api matches that email to the token's user name (`preferred_username`, or `upn` in v1 tokens) on the person's first sign-in only. A tenant admin can rename a user before that first sign-in, and a renamed user could then claim a record meant for someone else. After the first sign-in only the account's object id counts, so a later rename changes nothing. platform-api refuses an issuer that serves every tenant (`common`, `organizations`, `consumers`), and a token whose `tid` names another tenant than the issuer. Keep the tenant's admins few, and ask people to sign in soon after they are added.

## Register the app for the Portal

1. Open **App registrations** and select **New registration**.
2. Name it, for example `Workflow Portal`. Select **Accounts in this organizational directory only**.
3. Under **Redirect URI**, select **Single-page application** and enter `https://<portal-host>/auth/callback`. Select **Register**.
4. Copy its **Application (client) ID**.
5. Open **Authentication**. Under the single-page application platform, add a second redirect URI, `https://<portal-host>/signed-out`. Entra sends people there after they sign out.
6. Open **API permissions**. Select **Add a permission**, then **My APIs**, then the platform-api app. Select the delegated permission `access_as_user` and add it. Then select **Grant admin consent**.

The Portal app has no client secret. It uses PKCE, which needs no secret.

## Give the deploy its values

| Setting | Service | Value |
|---|---|---|
| `AUTH_MODE` | platform-api | `oidc` |
| `PUBLIC_BASE_URL` | platform-api | `https://<portal-host>` |
| `OIDC_ISSUER` | platform-api | `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| `OIDC_AUDIENCE` | platform-api | the platform-api app's Application (client) ID |
| `OIDC_AUTHORITY` | Portal | the same value as `OIDC_ISSUER` |
| `OIDC_CLIENT_ID` | Portal | the Portal app's Application (client) ID |
| `OIDC_SCOPE` | Portal | `openid profile offline_access api://<api-client-id>/access_as_user` |
| `FIRST_OPERATOR` | platform-api | the work email of the first Operator |
| `FIRST_APPROVERS` | platform-api | the work emails of the first two Approvers, separated by a comma. They must be two different people. The first Operator may be one of them |

`FIRST_OPERATOR` and `FIRST_APPROVERS` are read only while the People list is empty. After that platform-api ignores them, so a later deploy cannot hand out roles. If both are unset on an empty list, platform-api starts and logs a warning, and nobody can sign in until they are set.

`OIDC_JWKS_URL` is optional. Leave it unset, and platform-api reads the key address from the issuer's discovery document.

Never set `OIDC_TEST_ONLY_HTTP_ISSUER` or `OIDC_TEST_ONLY_HTTP_AUTHORITY` in a shared deployment. They exist for the mock identity provider in local tests, and platform-api refuses to start with the first one unless `PUBLIC_BASE_URL` is on localhost.

The Terraform variables that feed these settings are:

| Terraform variable | Sets |
|---|---|
| `oidc_issuer` | `OIDC_ISSUER` and `OIDC_AUTHORITY` |
| `oidc_audience` | `OIDC_AUDIENCE` |
| `oidc_jwks_url` | `OIDC_JWKS_URL`, only when it is not empty. Empty by default |
| `oidc_client_id` | `OIDC_CLIENT_ID` (the Portal app) |
| `oidc_scope` | `OIDC_SCOPE` |
| `first_operator` | `FIRST_OPERATOR`. Empty by default. Set it and `first_approvers` together, or leave both empty |
| `first_approvers` | `FIRST_APPROVERS`. Empty by default. Terraform refuses a value that does not name two different people |

Terraform sets the other two settings itself, with no variable. `AUTH_MODE` is always `oidc`, because dev mode refuses to start anywhere but localhost. `PUBLIC_BASE_URL` is the Portal's address, `https://portal.<domain>`, built from the Container Apps environment's default domain, which nobody knows before the first deploy. The deploy workflow fills each variable from the `azure-dev` environment's setting of the same name in capitals, such as `OIDC_SCOPE`.

None of these values is a secret key, so none needs Key Vault. `first_operator` and `first_approvers` name people, so both variables are marked sensitive in `infra/envs/dev/variables.tf`.

## Check the setup

1. Open `https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration` in a browser. Its `issuer` must equal `OIDC_ISSUER` exactly.
2. Open the Portal as one of the people named in `FIRST_OPERATOR` or `FIRST_APPROVERS`. You should go to the Microsoft sign-in page and come back signed in, with your name and roles in the header. platform-api matched your token's user name to the email in the People list on this first sign-in, and from now on matches your account's object id alone.
3. Open the Portal as an assigned person who is not on the list. You should see "Ask an Operator to add you". An Operator adds them under Settings, People and roles.
4. If the Portal keeps asking you to sign in again, the platform-api log names the reason it refused the token. The usual causes are a missing step 4 in the platform-api registration (the issuer is wrong), an `OIDC_AUDIENCE` set to the `api://` URI instead of the client ID, or a person with no assignment.
