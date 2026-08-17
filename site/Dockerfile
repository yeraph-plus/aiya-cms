FROM node:24-alpine AS build

WORKDIR /app
ARG SITE_BUILD_ENVIRONMENT=production
ARG SITE_BUILD_ORIGIN=https://www.example.com
ENV ASTRO_TELEMETRY_DISABLED=1 \
    SITE_ENVIRONMENT=${SITE_BUILD_ENVIRONMENT} \
    SITE_ORIGIN=${SITE_BUILD_ORIGIN}

COPY site/package.json site/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY site/ ./
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine AS runtime

WORKDIR /app
ENV HOST=0.0.0.0 \
    PORT=4321 \
    NODE_ENV=production

COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist

USER node
EXPOSE 4321

CMD ["node", "./dist/server/entry.mjs"]
