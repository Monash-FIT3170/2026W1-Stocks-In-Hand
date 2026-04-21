FROM node:20-alpine AS production
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
RUN npm run build

FROM production AS testing
