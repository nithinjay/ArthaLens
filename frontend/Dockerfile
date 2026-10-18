# syntax=docker/dockerfile:1
# ArthaLens web UI: static build served by nginx, which also proxies /api to the backend
# so the browser only ever talks to one origin. Build context: repository root.

FROM node:22.23.2-bookworm-slim AS build
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages/contracts/package.json packages/contracts/
COPY frontend/package.json frontend/
RUN pnpm install --frozen-lockfile --filter "@arthalens/frontend..."
COPY packages/contracts packages/contracts
COPY frontend frontend
RUN pnpm --filter "@arthalens/frontend..." build

FROM nginx:1.30.6-alpine AS runtime
COPY infrastructure/docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/"]
