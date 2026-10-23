# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f portal/Dockerfile -t portal .
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build
WORKDIR /repo/portal
COPY portal/package.json portal/package-lock.json portal/.npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts
COPY contracts /repo/contracts
COPY portal ./
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10 AS serve
ENV PORTAL_MODE=live \
    API_UPSTREAM=http://platform-api:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    PORTAL_CONFIG_AUTH="" \
    PORTAL_CSP_AUTH=""
COPY portal/nginx/nginx.conf /etc/nginx/nginx.conf
COPY portal/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 portal/nginx/16-portal-auth.envsh /docker-entrypoint.d/
COPY --from=build /repo/portal/dist /usr/share/nginx/html
# The entrypoint renders templates into conf.d as the running user, so that folder must be writable.
RUN rm -f /etc/nginx/conf.d/default.conf && chown nginx:nginx /etc/nginx/conf.d
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
