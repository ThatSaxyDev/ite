# Production Deployment

This is the minimum deployment path for the BYOK-first iTE launch.

Target state:

- `ite-cloud-api` runs as a single Node service with persistent storage for SQLite.
- `ite-cloud-web` is deployed as a static SPA.
- Core product promise is: sign in through the web, configure your own provider in `ite`, and use iTE immediately.

## Components

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
- `SQLITE_PATH` should point at persistent storage such as `/data/ite-cloud-api.sqlite`.

Important:

- The API container runs Better Auth migration before starting the server.
- Do not deploy this container without a persistent volume for `/data`.

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

## Production checklist

1. Create `.env.production` for `ite-cloud-api` from `.env.production.example`.
2. Create production web env from `ite-cloud-web/.env.production.example`.
3. Deploy API with a persistent volume mounted at `/data`.
4. Deploy web with `VITE_API_URL` set to the API origin.
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
