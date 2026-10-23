---
status: proposed
---

# Host the Portal as a Container App, not on Static Web Apps

ADR 0004 and the walking skeleton design put the Portal on Azure Static Web Apps. The Portal is more than static files, though. Its nginx sends `/api` to platform-api with buffering off, so the live activity view can stream server-sent events (SSE) for up to an hour. It also sets a strict Content Security Policy and other security headers on every response.

Static Web Apps cannot carry that stream. Microsoft's [API overview for Static Web Apps](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-overview) says that "the maximum duration of each API request [is] 45 seconds". A live view that drops every 45 seconds is not a live view. The same page says that linking our own API needs the Standard plan, and the [Container Apps page](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-container-apps) says that a linked container app then only accepts requests that come through the static web app. Static Web Apps can set the CSP through `globalHeaders` in `staticwebapp.config.json`, so the headers alone would not decide this. We read these limits in the docs and did not test them on Azure, because nothing in this change contacts Azure.

So the Portal ships the image it already has, as a fourth Container App with external ingress. Its nginx proxies `/api` to platform-api over HTTPS inside the Container Apps environment. The same `default.conf.template` serves Compose and Azure.

## Considered options

- **Static Web Apps Standard, linked to platform-api.** It is the documented path, but the 45-second limit breaks SSE. It also costs about USD 9 a month, against about USD 0 to 6 for a Container App that scales to zero (an estimate).
- **Static Web Apps Free for the files, with the browser calling platform-api directly.** This keeps the cheap host. But it needs CORS on platform-api, a second origin in the CSP's `connect-src`, and Portal code that knows the API's address. Locally the Portal and the API share one origin, so this would also split the dev and Azure setups.

## Consequences

- One image and one nginx config run the Portal everywhere. The CSP, security headers and SSE settings that CI's DAST scan checks are the same ones that run on Azure.
- Container Apps ingress stops any HTTP request after 240 seconds, according to the [ingress overview](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview). The SSE stream goes through two ingress hops, so the live view must reconnect at least every 4 minutes. The browser's `EventSource` reconnects on its own. Someone should confirm on the first deploy that the live view resumes without gaps.
- nginx now sends the TLS server name to the upstream (`proxy_ssl_server_name on`), because Container Apps routes HTTPS by that name. It changes nothing for the plain-HTTP upstream in Compose.
- The Portal scales to zero when idle, so the first page load after a quiet spell waits a few seconds for a replica to start.
- If this is accepted, update ADR 0004, the Portal row in the walking skeleton design's container table, and the "Deployment planned" diagram.
