# syntax=docker/dockerfile:1
# ArthaLens backend API. Build context: repository root (needs the pnpm workspace).

FROM node:22.23.2-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /repo

# Manifests only, so dependency layers are cached across code changes.
FROM base AS manifests
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages/contracts/package.json packages/contracts/
COPY packages/policy/package.json packages/policy/
COPY backend/package.json backend/

FROM manifests AS build
RUN pnpm install --frozen-lockfile --filter "@arthalens/backend..."
COPY packages/contracts packages/contracts
COPY packages/policy packages/policy
COPY backend backend
RUN pnpm --filter "@arthalens/backend..." build

FROM manifests AS prod-deps
RUN pnpm install --frozen-lockfile --prod --filter "@arthalens/backend..."

FROM node:22.23.2-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /repo
COPY --from=prod-deps /repo/node_modules node_modules
COPY --from=prod-deps /repo/backend/node_modules backend/node_modules
COPY --from=build /repo/packages/contracts/package.json packages/contracts/
COPY --from=build /repo/packages/contracts/dist packages/contracts/dist
# The exclusion policy is read at startup; the service refuses to start without it.
COPY --from=build /repo/packages/policy/package.json /repo/packages/policy/exclusions.v1.json packages/policy/
COPY --from=build /repo/packages/policy/dist packages/policy/dist
COPY --from=build /repo/backend/package.json backend/
COPY --from=build /repo/backend/dist backend/dist
USER node
WORKDIR /repo/backend
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "dist/server.js"]
