# iTE Ship Plan for April 16-17, 2026

This is the fastest credible path to launch iTE in a BYOK-first form by the end of Thursday, April 16, 2026 or by Friday morning, April 17, 2026.

## Launch decision

Ship the narrow product slice that already has working shape in this repo:

- `ite` is the product.
- BYOK is the default and only promise.
- `ite-cloud-api` exists to handle auth, browser approval, terminal sessions, refresh, and account session management.
- `ite-cloud-web` exists to handle login, CLI approval, and account session visibility.
- Bundled inference and paid plans are explicitly not part of the launch promise.

If a feature is not required for a user to install `ite`, sign in, run `/setup`, add their own provider key, and complete one successful prompt, it does not block launch.

## What is already true in this repo

Verified locally on April 16, 2026:

- Root app exists as a Python package published from `pyproject.toml`.
- `ite-cloud-api` builds successfully with `npm run build`.
- `ite-cloud-web` builds successfully with `npm run build`.
- API health route exists at `GET /health`.
- Web settings copy already says BYOK setup lives in the app and uses `/setup`.
- Production deployment docs already exist for the API and web.

## What is not release-green yet

The root Python test suite is not currently green in this checkout.

Local result on April 16, 2026:

- `468 passed`
- `26 failed`

Current high-signal failures:

- recent agent tests fail because mocked `chat_completion(...)` implementations do not accept the new `visual_budget` argument
- one reup model-picker test fails because the expected bundled model ordering no longer matches actual behavior

This means the launch path is still viable, but only if we treat these failures as a real pre-launch stabilization task instead of assuming the app is already release-ready.

## Launch promise

Public launch copy should say exactly this in substance:

- iTE is available now in BYOK mode.
- You can sign in, connect your own provider, and use the product immediately.
- Paid plans and bundled model access are coming later.
- Provider keys are configured inside the CLI or desktop app for now, not in the web account settings.

Do not promise:

- hosted provider-key management in the web app
- stable bundled inference for everyone
- production billing flow unless it is fully tested on the real domain

## Minimum production architecture

Keep production architecture boring for this launch:

- one always-on host for `ite-cloud-api`
- persistent storage mounted for the SQLite database
- one static deploy for `ite-cloud-web`
- one static deploy for the landing site if you want a separate marketing page

Hard rules:

- do not deploy the API on ephemeral storage while SQLite is the source of truth
- do not launch the API until `WEB_ORIGIN` and `BETTER_AUTH_URL` match real public domains
- do not block the core product on billing or bundled-provider configuration

## Environment checklist

### API

- `HOST`
- `PORT`
- `WEB_ORIGIN`
- `BETTER_AUTH_SECRET`
- `BETTER_AUTH_URL`
- `SQLITE_PATH`
- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`

Optional for later, not launch-critical:

- `POLAR_*`
- bundled provider keys and base URLs

### Web

- `VITE_API_URL`

### Landing site

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- optional `RESEND_API_KEY`
- optional `WAITLIST_FROM_EMAIL`

## Must-pass production test

This is the release gate. Do it on production, not localhost.

1. Install `ite` on a clean machine.
2. Start `ite`.
3. Trigger sign-in.
4. Browser opens the real production web app.
5. User completes sign-in.
6. Terminal receives valid session credentials.
7. User runs `/setup`.
8. User enters their own provider base URL, API key, and model.
9. User submits a real prompt and gets a real answer.
10. Restart `ite`.
11. Session remains usable or refresh succeeds cleanly.
12. Browser account page can list and revoke that session.

If any step fails, do not launch publicly.

## Today: execution order

### Phase 1: scope freeze

Time budget: 30-45 minutes

- Freeze the launch as BYOK-only.
- Remove or hide any paid or bundled messaging that reads as generally available.
- Decide whether the landing site is part of launch day or whether `ite-cloud-web` is enough.

### Phase 2: infra setup

Time budget: 1-2 hours

- Provision the API host with persistent disk.
- Set the API environment variables.
- Provision the static web deployment.
- Point the web build at the API origin with `VITE_API_URL`.
- Configure the real domains and TLS.

### Phase 3: auth and session validation

Time budget: 1 hour

- Run Better Auth migration against the production SQLite database.
- Verify `GET /health`.
- Verify browser login on the real domain.
- Verify CLI device/browser approval flow on the real domain.
- Verify session refresh and revoke.

### Phase 4: root app stabilization

Time budget: 2-4 hours

- Fix the Python test regressions caused by the `visual_budget` call signature change.
- Fix the failing model-picker expectation or restore intended ordering behavior.
- Re-run the root test suite until it is green.

This is the only part that currently looks like a real product-quality blocker in the repo.

### Phase 5: golden-path smoke test

Time budget: 30-60 minutes

- Install from the actual distribution path you plan to share.
- Sign in from a clean machine.
- Complete `/setup` with a real BYOK provider.
- Run a real prompt.
- Restart and re-verify session continuity.

### Phase 6: launch materials

Time budget: 30 minutes

- Update README or launch page copy to say BYOK-first.
- Write a short install + sign-in + `/setup` quickstart.
- Write a fallback support note for auth failures and invalid provider keys.

## Tomorrow morning launch criteria

Launch on Friday morning, April 17, 2026 only if all are true:

- `ite-cloud-api` is deployed on persistent storage
- `ite-cloud-web` is deployed on the real public domain
- auth callback URLs are correct
- clean-machine sign-in works
- `/setup` works
- BYOK prompt succeeds
- restart/refresh works
- session revocation works
- launch messaging matches actual product scope
- root app stabilization work is done or the remaining failures are proven non-user-facing

Do not launch if any are false.

## Fastest fallback if time slips tonight

If the app is not stable enough for a broad push by late tonight:

- still deploy the API and web
- keep the launch private or limited
- onboard a few real users manually
- collect auth and BYOK issues overnight
- launch publicly after the first successful clean-machine runs are repeatable

That is much better than announcing a broken “full platform” on April 16, 2026.

## Recommended owner checklist

If you are doing this mostly solo, treat the work in this order:

1. Production domains and env vars
2. API deployment with persistent SQLite
3. Web deployment wired to API
4. Auth/device/session validation
5. Root app test regression fixes
6. Clean-machine BYOK smoke test
7. Public launch copy

## Bottom line

The product that can realistically ship first is not “the whole platform.”
It is:

- install `ite`
- sign in through the hosted auth flow
- run `/setup`
- use your own model provider

Everything else should either be hidden, labeled as upcoming, or cut from the launch story.
