# syntax=docker/dockerfile:1
FROM node:20-alpine AS base
WORKDIR /app
# Evita stalls de IPv6 ao resolver registry.npmjs.org dentro do container
ENV NODE_OPTIONS=--dns-result-order=ipv4first

# --- deps: instala node_modules uma única vez (compartilhado por dev e builder) ---
FROM base AS deps
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# --- dev: hot reload, código montado via volume ---
FROM base AS dev
COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json ./
EXPOSE 3000
CMD ["npm", "run", "dev"]

# --- builder: build de produção ---
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# --- runner: imagem final standalone ---
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
