# Production-minded multi-stage build (Phase 14 spec §38). No secrets
# baked in — only NEXT_PUBLIC_AGENTABI_API_URL, which is safe for the
# browser by design (spec §9/§40).

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_AGENTABI_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_AGENTABI_API_URL=$NEXT_PUBLIC_AGENTABI_API_URL
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
# No `public/` directory exists in this app (no static assets, no
# next/image usage, no favicon) — see docs/DECISIONS.md. Copying it
# unconditionally broke the build the moment that stayed true; add the
# COPY back if/when a real public/ directory is introduced.
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
USER nextjs
EXPOSE 3000
CMD ["npm", "run", "start"]
