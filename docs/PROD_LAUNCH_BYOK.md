# iTE BYOK-First Production Launch

Target launch window: April 13, 2026 morning (Africa/Lagos)

## Release cut

Ship the smallest product slice that is already technically close:

- Root `ite` app ships as the primary product.
- BYOK is the default path on day one.
- Cloud auth ships for sign-in, browser approval, terminal session issuance, refresh, and session management.
- Cloud web ships as account/auth/session UI.
- Bundled inference remains behind Pro entitlement and is not required for launch readiness.
- Web-managed BYOK is out of scope for this launch because there is no implemented account settings flow for provider keys yet.

If a feature is not necessary for a user to install `ite`, sign in, configure their own provider key, and complete a successful first prompt, it should not block this launch.

## Current status

Verified on April 12, 2026:

- Root Python test suite passes: `472 passed`.
- `ite-cloud-api` production build passes.
- `ite-cloud-web` production build passes.
- Root app setup wizard already supports OpenAI-compatible BYOK configuration.
- Cloud API already supports browser auth, device flow, terminal session refresh, session revocation, usage, billing, and bundled inference routes.

One code fix was required and has been applied:

- `src/ite/ui/reup/app.py` now safely skips empty-state refresh when the Textual screen stack is not mounted, which removed a failing headless regression test.

## Must-do before launch

## 1. Lock the product story

- Public launch message must say BYOK first.
- Free plan messaging must emphasize local models + your own keys.
- Pro and bundled inference must be framed as upcoming or limited beta unless provider operations are fully ready.
- Remove any copy that implies account settings already manage provider keys in the web app.

## 2. Choose and configure production hosting

Minimum deployment set:

- `ite-cloud-api`: one always-on Node host with persistent disk access for SQLite, or move SQLite to a managed database immediately.
- `ite-cloud-web`: static hosting with `VITE_API_URL` pointed at the API origin.

Do not launch the API on purely ephemeral storage if SQLite remains the source of truth.

## 3. Set production environment variables

API:

- `HOST`
- `PORT`
- `WEB_ORIGIN`
- `BETTER_AUTH_SECRET`
- `BETTER_AUTH_URL`
- `SQLITE_PATH`
- `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` if GitHub auth is part of launch
- `POLAR_*` only if checkout and subscription management are actually enabled

Web:

- `VITE_API_URL`

Bundled provider env vars are optional for this launch if bundled inference is not part of the promise.

## 4. Prove the golden path end to end

This is the non-negotiable release test:

1. Fresh machine installs `ite`.
2. User launches `ite`.
3. User signs in through the browser flow.
4. User either completes setup wizard or runs `/setup`.
5. User enters their own provider base URL, API key, and model.
6. User submits a real prompt and receives a successful response.
7. User refreshes session or restarts `ite` and remains in a valid state.

Run this on production, not local.

## 5. Reduce blast radius

- Default launch should not depend on bundled inference providers being configured.
- Do not gate core CLI usage behind billing.
- If Polar is not fully tested in production, disable upgrade CTA instead of shipping broken checkout.
- Keep health checks simple and wire hosting health probes to `/health`.

## Should-do tonight

These improve launch quality but should only happen after the must-do list:

- Add a real production deployment doc for API and web.
- Add a release smoke-test checklist for auth, sessions, and BYOK.
- Audit marketing and account copy so it matches the BYOK-first cut.
- Add production logging review for auth failures and inference failures.
- Verify CORS and Better Auth callback URLs against the real web domain.

## Not for tomorrow morning

These are real tasks, but they should not block the April 13, 2026 morning release:

- Web account settings for storing provider keys.
- Full bundled inference rollout with hard provider SLAs.
- Advanced billing automation beyond basic sync and portal checks.
- Multi-region infra, background jobs, or database migrations beyond what is required to stay stable on one production environment.

## Recommended overnight sequence

1. Deploy `ite-cloud-api` to a single production host with persistent storage.
2. Run Better Auth migration against the production SQLite database.
3. Deploy `ite-cloud-web` with the production API origin.
4. Verify browser auth callback and device flow on the real domain.
5. Run the golden-path BYOK test from a clean machine.
6. Review logs for auth, refresh, and inference failures.
7. Freeze scope.
8. Launch the BYOK-first cut.

## Go / no-go

Go only if all are true:

- Auth works on the production domain.
- CLI browser approval works end to end.
- BYOK setup works end to end.
- A real prompt succeeds in production.
- Session refresh works.
- Session revocation works from the account UI.

No-go if any are false:

- SQLite persistence is not guaranteed.
- Browser auth callback URLs are wrong.
- BYOK setup is broken on a clean machine.
- Launch messaging still promises web-managed provider settings or bundled inference availability that is not actually stable.
