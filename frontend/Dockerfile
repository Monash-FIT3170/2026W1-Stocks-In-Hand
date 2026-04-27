FROM node:20-alpine AS dev
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .

FROM dev AS production

RUN npm run build

FROM production AS testing
