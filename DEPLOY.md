# Deploying Magnitude

```
Browser ──▶ Vercel (Next.js, static pages)          https://<project>.vercel.app
   │
   └──HTTPS──▶ Render (Docker: rating service)       https://magnitude-api.onrender.com
                  ├──▶ Neon Postgres   (source of truth)
                  └──▶ Upstash Redis   (cache, rate limits)
```

The frontend is fully static (every route prerenders), so any static or Next.js host works. Vercel is the default
here; Netlify instructions are at the end. The backend is the one Docker image in `backend/services/rating`, described
by `render.yaml` at the repo root.

## What's in the repo for this

| File | Purpose |
| --- | --- |
| `render.yaml` | Render Blueprint: one Docker web service on the free plan, health check `/healthz`, redeploys only when `backend/**` changes, secrets asked for in the dashboard |
| `backend/services/rating/start.sh` | Container entrypoint: runs `alembic upgrade head` when `RUN_MIGRATIONS=1`, then uvicorn on `$PORT`, trusting the proxy's `X-Forwarded-For` (so the sign-up limit sees real client IPs, not Render's proxy) |
| `backend/.dockerignore` | Keeps `.env` and `.venv` out of the build context |
| `vercel.json` | Next.js preset; skips a frontend build when a push only touched `backend/`, `render.yaml` or docs |
| `CORS_ORIGIN_REGEX` (backend setting) | Optional, lets preview deploys (whose URLs change) call the API |

## The manual steps

Do these in order. They take about 15 minutes. Pick one region for all three services; the examples use Singapore
(Render `singapore`, Neon and Upstash `AWS ap-southeast-1`). If you choose another region, change `region:` in `render.yaml`.

### 1. Push the code

Render and Vercel deploy from GitHub (`singhsrj/magnitude`, branch `main`). Commit and push everything first.

### 2. Neon (Postgres)

1. https://console.neon.tech → **New project**, region AWS Asia Pacific (Singapore).
2. **Connect** → copy two connection strings:
   - **pooled** (toggle "Connection pooling" on; the host contains `-pooler`) → this becomes `DATABASE_URL`
   - **direct** (toggle off) → this becomes `DIRECT_DATABASE_URL`

   Keep `?sslmode=require` on both; the app adjusts them for asyncpg.

If `backend/.env` already points at a Neon database you want to keep, reuse those two strings.

### 3. Upstash (Redis)

1. https://console.upstash.com → **Create database**, same region, TLS on.
2. Copy the **TCP** endpoint in `rediss://default:<password>@<host>.upstash.io:6379` form (not the REST URL)
   → this becomes `REDIS_URL`.

### 4. Render (backend)

1. https://dashboard.render.com → **New** → **Blueprint** → connect GitHub and pick the repo. Render reads `render.yaml`.
2. It asks for the `sync: false` values:
   | Key | Value |
   | --- | --- |
   | `DATABASE_URL` | Neon pooled string |
   | `DIRECT_DATABASE_URL` | Neon direct string |
   | `REDIS_URL` | Upstash `rediss://…` string |
   | `CORS_ORIGINS` | `https://<project>.vercel.app`. Choose the Vercel project name now (for example `magnitude`); you can fix it in step 6 |
   | `CLERK_PUBLISHABLE_KEY` | the Clerk `pk_...` publishable key (the same one Vercel gets in step 5). The service uses it to verify sign-ins. Leave empty to disable accounts |
   | `CORS_ORIGIN_REGEX` | leave empty for now (see step 6) |
3. **Apply.** The first build takes a few minutes. Migrations run when the container starts (`RUN_MIGRATIONS=1`).
4. Note the service URL Render shows (`https://magnitude-api.onrender.com`, or with a suffix if that name is taken). Check it:
   ```bash
   curl https://<render-url>/readyz        # {"redis":true,"database":true}
   ```
   If either value is `false`, the logs (Render → service → Logs) show which connection string is wrong.

### 5. Vercel (frontend)

1. https://vercel.com/new → import the repo. Framework: **Next.js** (detected), root directory: the repo root, build
   settings: defaults.
2. **Environment Variables** (set them for Production, and also for Preview if previews should sync):
   | Key | Value |
   | --- | --- |
   | `NEXT_PUBLIC_API_URL` | `https://<render-url>` (no trailing slash) |
   | `NEXT_PUBLIC_SYNC` | `on` |
   | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | from the Clerk dashboard > API keys |
   | `CLERK_SECRET_KEY` | same place; server only, never prefix it with `NEXT_PUBLIC_` |

   Clerk's temporary development keys work on localhost and deployed previews with a "Development mode" banner; for a real launch create a production instance (`npx clerk@latest deploy`), which needs a domain you own, not `*.vercel.app`.
3. **Deploy.** `NEXT_PUBLIC_*` values are baked in at build time: if you change one later, redeploy.

### 6. Connect the two

On Render → service → **Environment**, make `CORS_ORIGINS` the exact production URL Vercel gave you, for example
`https://magnitude.vercel.app` (scheme included, no trailing slash, comma-separate several, and add a custom domain
here if you attach one). Saving redeploys the service.

Optional, for preview deploys: Vercel names them `<project>-<hash>-<team>.vercel.app` and
`<project>-git-<branch>-<team>.vercel.app`. Allow them with:

```
CORS_ORIGIN_REGEX=^https://magnitude-[a-z0-9-]+-<team>\.vercel\.app$
```

where `<team>` is your Vercel account or team slug as it appears in a preview URL. Ending on the team slug stops other
people's `magnitude-*` projects from matching. (That would be low risk anyway: the API uses bearer tokens, not cookies.)

### 7. Check it works

1. Open the Vercel URL. The dashboard loads instantly from local data and creates an account in the background.
2. Play 5 practice rounds. DevTools → Network should show `POST /v1/sessions` and then `POST /v1/sync` with status 200.
   No request starts while a question is on screen.
3. Reload: the rating should come back from the server (`GET /v1/profile`).
4. A CORS error in the console means `CORS_ORIGINS` doesn't exactly match the page's origin.

Progress made on this site before sync was turned on is imported once, when the account is created.

## Sign-in (Clerk)

The browser signs in with Clerk and sends Clerk's session token to the API; the API checks its signature against Clerk's
published keys (derived from `CLERK_PUBLISHABLE_KEY`) and that the token was issued to one of `CORS_ORIGINS`.
So the page's exact origin must be in `CORS_ORIGINS` (or match `CORS_ORIGIN_REGEX`), or signed-in requests are refused
with `token was issued for a different site`. Clerk development keys work for a first deploy; switch to a production
instance (`npx clerk@latest deploy`, needs a domain you own) before real users, and update the key in both places.

## Free-plan behaviour

- **Render free sleeps after 15 minutes idle**, and the next request takes roughly a minute to wake it. Play isn't
  affected once you've visited: the browser keeps spare session tickets and an outbox, so answers queue and sync when the
  server is up. Only a first-ever visit to a sleeping server waits on "Connecting…". The dashboard wakes the server as
  soon as it loads.
  To avoid this, either upgrade the service to **Starter**, or ping `https://<render-url>/healthz` every 10 minutes
  from an external cron (for example cron-job.org). One always-on free service fits in Render's monthly free hours.
- **Neon** suspends an idle database too; the first query after that adds a second or two. The service is built for it
  (pre-ping, 15 s connect timeout).
- **Upstash free** has a monthly command quota. The app uses a handful of commands per sync and doesn't poll.

## Day-to-day

- Push to `main`: Render redeploys if `backend/**` or `render.yaml` changed; Vercel rebuilds unless only those (or
  `*.md`) changed. Both keep the previous version live until the new one is healthy.
- **Migrations** run at container start. On a paid plan, switch to Render's pre-deploy step instead: uncomment
  `preDeployCommand` in `render.yaml` and set `RUN_MIGRATIONS=0`. Do that before scaling past one instance, since
  start-up migrations on several instances would race.
- **Logs:** Render → service → Logs. A synced round the server couldn't reproduce logs at ERROR with `mismatch`, which
  means an engine parity bug: run the parity tests.
- **Rollback:** Render → Events → pick an earlier deploy → Rollback. Vercel → Deployments → Promote. Migrations
  are forward-only, so roll the schema back by hand (`alembic downgrade`) only if a migration itself was the problem.

## Netlify instead of Vercel

Netlify detects Next.js and uses its Next runtime automatically. **Add new site** → import the repo → build command
`npm run build` (the default) → the same two environment variables → deploy. Then set `CORS_ORIGINS` to
`https://<site>.netlify.app`. Its preview URLs are `https://deploy-preview-<n>--<site>.netlify.app`, which matches
`CORS_ORIGIN_REGEX=^https://deploy-preview-[0-9]+--<site>\.netlify\.app$`. `vercel.json` is ignored there, so
Netlify also rebuilds on backend-only pushes (harmless).

## Trying the production setup locally

```bash
cd backend && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres redis
docker build -f services/rating/Dockerfile -t magnitude-api .
docker run --rm --network magnitude_default -p 10000:10000 -e PORT=10000 -e RUN_MIGRATIONS=1 \
  -e DATABASE_URL=postgresql://postgres:postgres@postgres:5432/magnitude -e REDIS_URL=redis://redis:6379/0 \
  -e CORS_ORIGINS=http://localhost:3000 magnitude-api
E2E_API_URL=http://localhost:10000 npm run e2e:sync      # from the repo root
```
