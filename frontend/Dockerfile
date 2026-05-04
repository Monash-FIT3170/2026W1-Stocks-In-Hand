FROM node:20-alpine AS dev
WORKDIR /app
COPY package.json .
RUN --mount=type=cache,target=/root/.npm npm install
COPY . .

FROM dev AS production

RUN --mount=type=cache,target=/app/.next/cache npm run build

FROM production AS testing
