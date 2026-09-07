# Deploying to Railway

Four Railway services: managed Postgres, managed Redis, the backend (Dockerfile),
and the frontend (Dockerfile). Backend and frontend get separate Railway
domains — see `http.ts`'s `VITE_API_ORIGIN` and `auth_routes.py`'s
`SameSite=None` cookie for why that's safe cross-origin.

## Order of operations matters here

Backend needs to exist (and have a domain) before the frontend can be built,
because `VITE_API_ORIGIN`/`VITE_WS_ORIGIN` are baked into the frontend's JS
at **build** time, not read at runtime. But backend's `ALLOWED_ORIGINS` needs
the frontend's domain, which doesn't exist until frontend deploys once. So:
backend first (without `ALLOWED_ORIGINS` set correctly yet) → frontend →
back to backend to fix `ALLOWED_ORIGINS` → redeploy backend (just an env var
change, no rebuild).

## 1. Create the project and add the databases

1. New Railway project → **New → Database → Add PostgreSQL**.
2. **New → Database → Add Redis**.

Both auto-generate connection strings (`DATABASE_URL`, `REDIS_URL`) scoped to
that plugin — you'll reference them from the backend service, not copy them
by hand.

## 2. Backend service

1. **New → GitHub Repo** → select this repo.
2. In the service's **Settings**:
   - **Root Directory**: `backend`
   - **Builder**: Dockerfile (set this explicitly — with both a `Dockerfile`
     and a `pyproject.toml` in the root directory, Railway's auto-detection
     can guess Nixpacks/Python instead of your Dockerfile).
3. In **Variables**, use the Raw Editor and paste:
   ```
   APP_ENV=production
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
   The `${{Postgres.DATABASE_URL}}` / `${{Redis.REDIS_URL}}` syntax is
   Railway's cross-service variable reference — it resolves to whatever
   those plugins actually generated, so you never hand-copy a password.
   (If your plugins aren't named exactly "Postgres"/"Redis", match whatever
   Railway shows in its variable picker.)
4. Deploy. Railway injects its own `PORT` automatically — `docker-entrypoint.sh`
   already binds to `${PORT:-8000}`, and `alembic upgrade head` runs before
   uvicorn starts on every deploy.
5. Once it's up: **Settings → Networking → Generate Domain**. Copy that URL
   (e.g. `api-production-xxxx.up.railway.app`) — you need it for the next step.

## 3. Frontend service

1. **New → GitHub Repo** → same repo again.
2. **Settings**:
   - **Root Directory**: `frontend`
   - **Builder**: Dockerfile
3. **Variables**:
   ```
   VITE_API_ORIGIN=https://<backend-domain-from-step-2.5>
   VITE_WS_ORIGIN=wss://<backend-domain-from-step-2.5>
   ```
   Railway passes service variables through as Docker build args automatically
   for Dockerfile builds, matching the `ARG VITE_API_ORIGIN` / `ARG VITE_WS_ORIGIN`
   already declared in `frontend/Dockerfile` — no extra config needed for that
   part.
4. Deploy. **Settings → Networking → Generate Domain** once it's up.

## 4. Close the loop on ALLOWED_ORIGINS

Back on the **backend** service → Variables → set:
```
ALLOWED_ORIGINS=https://<frontend-domain-from-step-3.4>
```
This is a plain env var change, not a build arg, so Railway just restarts the
container — no rebuild.

## 5. Verify

```
curl https://<backend-domain>/healthz
```
should return `{"status":"ok","checks":{"database":true,"redis":true}}`.
Then open the frontend URL, sign up, create a doc, and open the same doc in
a second browser to confirm real-time sync still works cross-origin.

## Logs & redeploys

- Logs: each service's **Deployments** tab → **View Logs**, or `railway logs`
  via the CLI (`railway login && railway link`).
- Redeploy after a `git push`: Railway auto-redeploys on push to the linked
  branch by default (configurable per service under Settings → Source).

## Custom domain (optional)

Both services support **Settings → Networking → Custom Domain** instead of
the `*.up.railway.app` one — Railway issues and renews the TLS cert for it
automatically, same as the `*.up.railway.app` domains. If you do this, update
`ALLOWED_ORIGINS`, `VITE_API_ORIGIN`, and `VITE_WS_ORIGIN` to match and
redeploy (the last two need a frontend rebuild, since they're baked in at
build time).
