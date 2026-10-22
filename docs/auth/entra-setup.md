# Set up Entra ID sign-in

This guide is for the person who holds admin rights in the Entra tenant. When you finish, people sign in to the Portal with their work account, and platform-api knows who is an Operator and who is an Approver. [ADR 0018](../adr/0018-sign-in-with-openid-connect.md) explains the design.

You register two apps. One is for platform-api, which owns the roles. One is for the Portal, which signs people in. You need the Portal's https address before you start. In this guide it is `https://<portal-host>`.

## Register the app for platform-api

1. In the Entra admin center, open **App registrations** and select **New registration**.
2. Name it, for example `Workflow platform API`. Select **Accounts in this organizational directory only**. Leave the redirect URI empty. Select **Register**.
3. Copy the **Application (client) ID** and the **Directory (tenant) ID** from the overview page.
4. Open **Manifest**. Set `requestedAccessTokenVersion` (under `api`) to `2`, then save. If you skip this step, tokens carry the old issuer `https://sts.windows.net/<tenant-id>/` and platform-api refuses every one of them.
5. Open **Expose an API**. Set the **Application ID URI** to the suggested `api://<api-client-id>`. Add a scope named `access_as_user`, with **Admins and users** able to consent, and save it.
6. Open **App roles** and create two roles. The values must match exactly, including the capital letter.

   | Display name | Value | Allowed member types |
   |---|---|---|
   | Operator | `Operator` | Users/Groups |
   | Approver | `Approver` | Users/Groups |

## Assign people

1. Open **Enterprise applications** and select the platform-api app.
2. In **Properties**, set **Assignment required** to **Yes**. Then only assigned people can get a token for platform-api.
3. In **Users and groups**, add one assignment for each person and role. A person who is both an Operator and an Approver needs two assignments.

A role change reaches the platform when the person's current token expires, so after at most about 90 minutes.

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

`OIDC_JWKS_URL` is optional. Leave it unset, and platform-api reads the key address from the issuer's discovery document.

Never set `OIDC_TEST_ONLY_HTTP_ISSUER` or `OIDC_TEST_ONLY_HTTP_AUTHORITY` in a shared deployment. They exist for the mock identity provider in local tests, and platform-api refuses to start with the first one unless `PUBLIC_BASE_URL` is on localhost.

The Terraform variables that feed these settings are:

| Terraform variable | Sets |
|---|---|
| `auth_mode` | `AUTH_MODE`, `oidc` in Azure |
| `public_base_url` | `PUBLIC_BASE_URL` |
| `oidc_issuer` | `OIDC_ISSUER` and `OIDC_AUTHORITY` |
| `oidc_audience` | `OIDC_AUDIENCE` |
| `oidc_jwks_url` | `OIDC_JWKS_URL`, empty by default |
| `oidc_client_id` | `OIDC_CLIENT_ID` (the Portal app) |
| `oidc_scope` | `OIDC_SCOPE` |

None of these values is a secret. They can live in plain Terraform variables, not in Key Vault.

## Check the setup

1. Open `https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration` in a browser. Its `issuer` must equal `OIDC_ISSUER` exactly.
2. Open the Portal as an assigned person. You should go to the Microsoft sign-in page and come back signed in, with your name and roles in the header.
3. If the Portal says the platform refused your sign-in, the platform-api log names the reason. The usual causes are a missing step 4 in the platform-api registration (the issuer is wrong), an `OIDC_AUDIENCE` set to the `api://` URI instead of the client ID, or a person with no assignment.
