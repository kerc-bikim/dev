FROM node:20-alpine AS build
WORKDIR /app
COPY backend/package.json backend/package-lock.json ./backend/
WORKDIR /app/backend
RUN npm ci
COPY backend/ ./
COPY shared /app/shared
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=build /app/backend /app/backend
COPY --from=build /app/shared /app/shared
WORKDIR /app/backend
ENV NODE_ENV=production PORT=8787
EXPOSE 8787
CMD ["node", "dist/index.js"]
