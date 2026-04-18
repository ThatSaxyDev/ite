# Production Deployment

This is the minimum deployment path for the current iTE launch on Render.

Target state:

- `ite-cloud-api` runs as one Render web service with a persistent disk for SQLite.
- `ite-cloud-web` is deployed as one Render static site.
- Core product promise is: sign in through the web, connect your model service in `ite`, and use iTE immediately.

## Render topology

- API origin: `https://api.example.com`
- Web origin: `https://app.example.com`
- SQLite path in production: `/data/ite-cloud-api.sqlite`

## API

Path: `ite-cloud-api`

Artifacts added:

- `Dockerfile`
- `.dockerignore`
- `.env.production.example`

Build locally:

```bash
cd ite-cloud-api
docker build -t ite-cloud-api .
```

Run locally as production-like:

```bash
docker run --rm \
  -p 4000:4000 \
  -v "$(pwd)/.data:/data" \
  --env-file .env.production \
  ite-cloud-api
```

Requirements:

- `WEB_ORIGIN` must be the real web app origin.
- `BETTER_AUTH_URL` must be the real API origin.
- `BETTER_AUTH_SECRET` must be a strong secret.
- `SQLITE_PATH` must point at the Render persistent disk, for example `/data/ite-cloud-api.sqlite`.

Important:

- The API container runs Better Auth migration before starting the server.
- Do not deploy this container without a persistent volume for `/data`.

Recommended Render settings:

- Service type: `Web Service`
- Runtime: `Docker`
- Persistent disk mount path: `/data`
- Health check path: `/health`
- Environment:
  - `HOST=0.0.0.0`
  - `PORT=4000`
  - `WEB_ORIGIN=https://app.example.com`
  - `BETTER_AUTH_URL=https://api.example.com`
  - `BETTER_AUTH_SECRET=<long random secret>`
  - `SQLITE_PATH=/data/ite-cloud-api.sqlite`
  - `GITHUB_CLIENT_ID=<github oauth id>`
  - `GITHUB_CLIENT_SECRET=<github oauth secret>`

## Web

Path: `ite-cloud-web`

Artifacts added:

- `Dockerfile`
- `nginx.conf`
- `.dockerignore`
- `.env.production.example`

Build locally:

```bash
cd ite-cloud-web
docker build \
  --build-arg VITE_API_URL=https://api.example.com \
  -t ite-cloud-web .
```

Run locally as production-like:

```bash
docker run --rm -p 3000:80 ite-cloud-web
```

Notes:

- The SPA fallback is handled by `nginx.conf`.
- `VITE_API_URL` must point at the deployed API origin.

Recommended Render settings:

- Service type: `Static Site`
- Root directory: `ite-cloud-web`
- Build command: `npm ci && npm run build`
- Publish directory: `dist`
- Environment:
  - `VITE_API_URL=https://api.example.com`

## GitHub OAuth

Set the GitHub OAuth callback URL to:

```text
https://api.example.com/api/auth/callback/github
```

If you also keep a local app for development, keep the local callback separately:

```text
http://127.0.0.1:4000/api/auth/callback/github
```

## Production checklist

1. Create `.env.production` for `ite-cloud-api` from `.env.production.example`.
2. Create production web env from `ite-cloud-web/.env.production.example`.
3. Create the Render API web service with a persistent volume mounted at `/data`.
4. Create the Render static site for `ite-cloud-web` with `VITE_API_URL` set to the API origin.
5. Confirm `https://api.../health` returns `ok: true`.
6. Confirm browser auth works on the real domain.
7. Confirm CLI device flow works on the real domain.
8. Confirm a fresh `ite` install can sign in, run `/setup`, enter a real provider key, and complete a prompt.

## Launch posture

For this release, do not block launch on:

- bundled inference provider readiness
- Polar checkout readiness
- web-managed provider key storage

If any of those are not production-ready, leave them disabled or message them as upcoming.
