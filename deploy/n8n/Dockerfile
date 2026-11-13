# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f deploy/n8n/Dockerfile -t wab/n8n .
# Node 26, as in n8n-node-pack/.nvmrc and in n8n 2.42.6 itself.
FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /pack
COPY n8n-node-pack/package.json n8n-node-pack/package-lock.json n8n-node-pack/.npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts
COPY n8n-node-pack/tsconfig.json n8n-node-pack/tsconfig.build.json ./
COPY n8n-node-pack/src ./src
RUN npm run build

# The base pin is also in infra/public-images.json; the n8n-node-pack CI job checks they match.
FROM n8nio/n8n:2.42.6@sha256:526daa38b68e923cc00c5280d18b4da5d489f115a73bdbf3b8e452b184197a9a
# Outside /home/node/.n8n, which is a volume, so a new image always brings its own pack.
COPY --from=build /pack/dist /opt/wab/n8n-nodes-wab
ENV N8N_CUSTOM_EXTENSIONS=/opt/wab/n8n-nodes-wab
