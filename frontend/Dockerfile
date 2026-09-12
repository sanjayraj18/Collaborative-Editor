# --- build: compile the static bundle ---
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .


ARG VITE_WS_ORIGIN
ENV VITE_WS_ORIGIN=${VITE_WS_ORIGIN}

ARG VITE_API_ORIGIN
ENV VITE_API_ORIGIN=${VITE_API_ORIGIN}


RUN set -e; \
    [ -n "$VITE_API_ORIGIN" ] || { echo "ERROR: VITE_API_ORIGIN must be set as a build arg" >&2; exit 1; }; \
    [ -n "$VITE_WS_ORIGIN" ]  || { echo "ERROR: VITE_WS_ORIGIN must be set as a build arg"  >&2; exit 1; }; \
    case "$VITE_WS_ORIGIN" in \
        wss://*) ;; \
        *) echo "ERROR: VITE_WS_ORIGIN must be wss:// (got: $VITE_WS_ORIGIN)" >&2; exit 1 ;; \
    esac

RUN npm run build


# --- serve: static files only, no node runtime ---
FROM caddy:2-alpine

COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 8080
