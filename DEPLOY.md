# Deploying to a single VPS

## Prerequisites

- A VPS (DigitalOcean, Hetzner, EC2, etc.) with Docker + Docker Compose plugin installed.
- A domain's DNS **A record** pointed at the VPS's public IP — do this first, since Caddy needs it resolvable to issue a TLS certificate.
- Ports 22, 80, and 443 open on the VPS firewall (e.g. `ufw allow 22,80,443/tcp`).

## First-time setup

1. Clone the repo onto the VPS:
   ```
   git clone <your-repo-url> collab && cd collab
   ```

2. Create the root env file from the template:
   ```
   cp .env.production.example .env
   ```
   Edit `.env`:
   - `POSTGRES_PASSWORD` — generate a real one (`python3 -c 'import secrets;print(secrets.token_urlsafe(32))'`).
   - `DOMAIN` — your real domain, e.g. `collab.example.com`.
   - `VITE_WS_ORIGIN` — `wss://` + that same domain.

3. Create the backend env file from its template:
   ```
   cp backend/.env.production.example backend/.env
   ```
   Edit `backend/.env`:
   - `SECRET_KEY` — generate a fresh one the same way (**never** reuse a dev value).
   - `ALLOWED_ORIGINS` — `https://` + your domain.
   - `DATABASE_URL` — replace the password segment with **the exact same** `POSTGRES_PASSWORD` you put in the root `.env`. These are two copies of one secret; if they don't match, Postgres starts fine but the backend can't authenticate to it.

4. Build and start everything:
   ```
   docker compose up -d --build
   ```
   The backend container won't start serving until Postgres and Redis report healthy (`depends_on: condition: service_healthy`), and it runs `alembic upgrade head` automatically before starting uvicorn — no manual migration step.

5. Watch it come up:
   ```
   docker compose logs -f
   ```
   Look for `op_log_writer_start`, `reaper_start`, `permission_checker_start`, and `Application startup complete` from the backend, and Caddy logging that it obtained a certificate for your domain.

6. Verify:
   ```
   curl https://yourdomain.com/api/healthz
   ```
   should return `{"status":"ok","checks":{"database":true,"redis":true}}`. Then open `https://yourdomain.com` in a browser and sign up.

## Redeploying after changes

```
git pull
docker compose up -d --build
```
Compose only rebuilds images whose build context actually changed, so this is cheap when you've only touched one side (frontend or backend).

## Logs

```
docker compose logs -f backend   # structured JSON, one line per event
docker compose logs -f frontend  # Caddy access/cert logs
```

## Backups

`postgres_data` is a named Docker volume — everything durable (users, documents, the op log, snapshots) lives there. At minimum, cron a periodic dump off the box:
```
docker compose exec postgres pg_dump -U collab collab > backup-$(date +%F).sql
```
This isn't automated yet — worth revisiting once there's real data worth losing.

## Rolling back

```
git checkout <previous-commit-or-tag>
docker compose up -d --build
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Caddy never gets a certificate | DNS hasn't propagated yet, or port 80/443 isn't actually open on the VPS firewall/cloud security group |
| Backend keeps restarting | Check `docker compose logs backend` — usually `DATABASE_URL`'s password doesn't match `POSTGRES_PASSWORD` |
| `docker compose up` fails to bind port 80/443 | Something else on the VPS (default nginx/apache) is already using it — stop it first |
| `/api/healthz` returns `"degraded"` | One of `database`/`redis` in the response body is `false` — check that container's logs specifically |
