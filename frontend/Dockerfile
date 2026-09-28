# ── Image frontend Next.js ──────────────────────────────────────────────────
# Étape 1 : build
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# URL de l'API vue DEPUIS LE NAVIGATEUR (pas depuis le conteneur)
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

# Étape 2 : exécution (image minimale)
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/next.config.ts ./

RUN adduser -D appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
