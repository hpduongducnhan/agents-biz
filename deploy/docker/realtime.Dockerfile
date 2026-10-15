# syntax=docker/dockerfile:1
# Service realtime — Node chạy thẳng TypeScript (type stripping), không bước build.
FROM node:26-slim
ENV NODE_ENV=production
WORKDIR /app/realtime
COPY realtime/package.json realtime/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev
COPY realtime/src ./src
USER node
EXPOSE 16813
CMD ["node", "src/main.ts"]
