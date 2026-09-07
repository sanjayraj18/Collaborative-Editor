# --- build: compile the static bundle ---
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .


ARG VITE_WS_ORIGIN
ENV VITE_WS_ORIGIN=${VITE_WS_ORIGIN}

RUN npm run build


FROM caddy:2-alpine

COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile