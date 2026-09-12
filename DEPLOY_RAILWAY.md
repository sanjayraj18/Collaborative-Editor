# Deploying to Railway

Four Railway services in one project: managed Postgres, managed Redis, the
backend (Dockerfile), and the frontend (Dockerfile). Backend and frontend get
separate Railway domains — see `http.ts`'s `VITE_API_ORIGIN` and
`auth_routes.py`'s `SameSite=None` cookie for why that's safe cross-origin.

Budget: Railway has no always-free tier. New accounts get a small trial credit;
past that it's the $5/month Hobby plan, and four services idling will consume
that. Plan on ~$5/mo to keep this reachable.

## Order of operations matters here

`VITE_API_ORIGIN`/`VITE_WS_ORIGIN` are baked into the frontend's JS at **build**
time, not read at runtime, so the backend needs a domain before the frontend can
be built. But the backend's `ALLOWED_ORIGINS` needs the frontend's domain, which
doesn't exist until the frontend deploys once. So: backend → frontend → back to
the backend to fix `ALLOWED_ORIGINS`. That last step is an env var change only,
so it restarts without a rebuild.

## 0. Push the deployment fixes first

Railway builds from GitHub, so anything not pushed isn't deployed:

```
git push origin main
```

## 1. Create the project and add the databases

1. New Railway project → **New → Database → Add PostgreSQL**.
2. **New → Database → Add Redis**.

Both auto-generate connection strings (`DATABASE_URL`, `REDIS_URL`) scoped to
that plugin — you'll reference them from the backend service, not copy them by
hand.

## 2. Backend service

1. **New → GitHub Repo** → select this repo.
2. In the service's **Settings**:
   - **Root Directory**: `backend`
   - **Builder**: Dockerfile. Set this explicitly — with both a `Dockerfile` and
     a `pyproject.toml` in the root directory, Railway's auto-detection can pick
     Nixpacks/Python instead of your Dockerfile.
3. In **Variables**, use the Raw Editor and paste:
   ```
   APP_ENV=production
   PORT=8000
   SECRET_KEY=<generate: python3 -c "import secrets;print(secrets.token_urlsafe(48))">
   ALLOWED_ORIGINS=https://placeholder-fix-after-frontend-deploys

   TICKET_TTL_SECONDS=30
   LOGIN_RATE_LIMIT=10
   LOGIN_RATE_WINDOW_SECONDS=300
   RATE_LIMIT_FAIL_OPEN=true

   JWT_ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=10
   REFRESH_TOKEN_EXPIRE_DAYS=30

   PING_INTERVAL_SECONDS=20
   PONG_TIMEOUT_SECONDS=45

   MAX_FRAME_BYTES=1048576
   SEND_QUEUE_MAX_FRAMES=256
   SEND_QUEUE_MAX_BYTES=8388608

   ROOM_INBOX_MAX_FRAMES=1024
   ROOM_IDLE_TTL_SECONDS=60
   REAPER_INTERVAL_SECONDS=10
   PERMISSION_CHECK_SECONDS=30
   RESUME_RING_SIZE=1024

   UPDATE_COALESCE_MS=20
   AWARENESS_COALESCE_MS=100

   OP_LOG_BATCH_MS=10
   SNAPSHOT_EVERY_N_OPS=500
   COMPACTION_INTERVAL_SECONDS=60

   DATABASE_URL=${{Postgres.DATABASE_URL}}
   REDIS_URL=${{Redis.REDIS_URL}}
   ```
   `APP_ENV=production` is load-bearing, not cosmetic: `auth_routes.py` sets the
   refresh cookie `secure=not settings.is_dev`, and browsers silently drop a
   `SameSite=None` cookie that isn't also `Secure`. Leave it at `dev` and login
   appears to succeed but the session never persists.

   `SECRET_KEY` must be at least 32 bytes — `config.py`'s validator rejects
   anything shorter and the container won't boot.

   The `${{Postgres.DATABASE_URL}}` / `${{Redis.REDIS_URL}}` syntax is Railway's
   cross-service reference: it resolves to whatever those plugins actually
   generated, so you never hand-copy a password. If your plugins aren't named
   exactly "Postgres"/"Redis", match whatever Railway shows in its variable
   picker. Railway hands out `postgres://` URLs and SQLAlchemy needs
   `postgresql://` — `config.py` rewrites the scheme, so paste it as-is.
4. Deploy. `docker-entrypoint.sh` runs `alembic upgrade head` before uvicorn on
   every deploy, retrying for ~30s so a cold Postgres or slow private-DNS
   doesn't fail the release.
5. Once it's up: **Settings → Networking → Generate Domain**, target port
   **8000**. Copy that URL (e.g. `api-production-xxxx.up.railway.app`) — the
   next step needs it.

## 3. Frontend service

1. **New → GitHub Repo** → same repo again.
2. **Settings**:
   - **Root Directory**: `frontend`
   - **Builder**: Dockerfile
3. **Variables**:
   ```
   PORT=8080
   VITE_API_ORIGIN=https://<backend-domain-from-step-2.5>
   VITE_WS_ORIGIN=wss://<backend-domain-from-step-2.5>
   ```
   Note the schemes: `https://` for the API, `wss://` for the socket. Plain
   `ws://` from an HTTPS page is blocked as mixed content and every document
   silently fails to sync.

   No trailing slash on either — `buildWsUrl` and axios's `baseURL` both append
   their own path.

   Railway passes service variables through as Docker build args for Dockerfile
   builds, matching the `ARG VITE_API_ORIGIN`/`ARG VITE_WS_ORIGIN` already
   declared in `frontend/Dockerfile`.
4. Deploy, then **Settings → Networking → Generate Domain**, target port
   **8080** (what `Caddyfile` falls back to when Railway doesn't inject `PORT`).

## 4. Close the loop on ALLOWED_ORIGINS

Back on the **backend** service → Variables → set:
```
ALLOWED_ORIGINS=https://<frontend-domain-from-step-3.4>
```
This gates two separate things: FastAPI's CORS middleware for `/api`, and the
`origin` header check in `ws/endpoint.py`. Get it wrong and the REST calls fail
first, so you may never reach a socket error. Comma-separate to allow more than
one origin; trailing slashes are stripped for you.

Plain env var, not a build arg, so Railway just restarts the container.

## 5. Verify

```
curl https://<backend-domain>/healthz
```
should return `{"status":"ok","checks":{"database":true,"redis":true}}`. A
`degraded` response still returns which dependency is false.

Then open the frontend URL, sign up, create a doc, and open that same doc in a
second browser to confirm real-time sync works cross-origin. Use a different
browser or a private window, not a second tab — two tabs in one profile share
a session and won't exercise the multi-user path.

## Logs & redeploys

- Logs: each service's **Deployments** tab → **View Logs**, or `railway logs`
  via the CLI (`railway login && railway link`). The backend logs structured
  JSON, one line per event; look for `op_log_writer_start`, `reaper_start`,
  `permission_checker_start`, and `Application startup complete`.
- Railway auto-redeploys on push to the linked branch (Settings → Source).
- Changing `VITE_*` needs a **rebuild**, not just a restart — they're compiled
  into the bundle. Use **Deploy** rather than **Restart** after touching them.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `exec format error` on boot | `docker-entrypoint.sh` lost its `#!/bin/sh` line, or was committed without the exec bit (`git update-index --chmod=+x`) |
| Container exits before logging anything | `SECRET_KEY` under 32 bytes, or `DATABASE_URL`/`REDIS_URL` unset — `config.py` validates at import, so it dies before the app starts |
| Build succeeds, `/healthz` says `degraded` | Read which of `database`/`redis` is `false`; usually the `${{Plugin.VAR}}` reference points at a plugin name that doesn't exist, which resolves to empty |
| Login works, but reloading logs you out | `APP_ENV` isn't `production`, so the refresh cookie isn't `Secure` and the browser drops it |
| API calls blocked by CORS | `ALLOWED_ORIGINS` still on the placeholder, or it has a trailing slash mismatch with the real frontend domain |
| Docs load but never sync between browsers | `VITE_WS_ORIGIN` is `ws://` instead of `wss://`, or missing from `ALLOWED_ORIGINS` (the WS handshake checks `origin` too) |
| Frontend deploys but serves nothing | Railway's generated domain targets the wrong port — Caddy listens on `PORT`, default 8080 |
| Everyone gets rate-limited at once | Proxy headers aren't trusted, so `ratelimit.py` keys every request to Railway's proxy IP. The entrypoint passes `--proxy-headers --forwarded-allow-ips='*'` to fix this |
| Migrations fail on first deploy only | Postgres wasn't accepting connections yet; the entrypoint retries 10× at 3s, so redeploy once |

## Custom domain (optional)

Both services support **Settings → Networking → Custom Domain** instead of the
`*.up.railway.app` one; Railway issues and renews the cert either way. If you
add one, update `ALLOWED_ORIGINS`, `VITE_API_ORIGIN`, and `VITE_WS_ORIGIN` to
match — and remember the last two need a frontend rebuild.
