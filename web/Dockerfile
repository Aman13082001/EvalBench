# The web app. Three stages so the runtime image carries neither the
# npm cache nor the toolchain — only the standalone server Next emits.

FROM node:20-alpine AS deps
WORKDIR /app
# Copy manifests alone so this layer is cached until dependencies
# actually change; editing a page must not re-run npm ci.
COPY package.json package-lock.json ./
RUN npm ci


FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, not read
# at runtime, so it has to arrive as a build arg. It is also the address
# the visitor's *browser* uses, not one resolved inside the compose
# network — "http://api:8000" would work from the container and fail in
# every browser. Default to the published host port.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_GRAFANA_URL=http://localhost:3000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_GRAFANA_URL=$NEXT_PUBLIC_GRAFANA_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3005
ENV HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# `standalone` bundles its own minimal node_modules, but .next/static is
# not part of it and has to be copied alongside or every asset 404s.
# (No public/ directory in this app, so there is nothing else to bring.)
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3005

CMD ["node", "server.js"]
