# OpenRouter Bundled Phase 1, Hosted Push And End-to-End Test

## Current Status

As of April 29, 2026, the Phase 1 implementation is in place across:

- `src/ite/` runtime
- `ite-cloud-api/` backend
- `ite-cloud-web/` web app
- `ite_remote/` mobile remote surface

Implemented now:

- bundled routing can run through `BUNDLED_PROVIDER_MODE=openrouter`
- bundled model catalog is backend-driven
- bundled source labels stay `Bundled` in the runtime picker
- same-name bundled and BYOK entries no longer collapse into one entry
- new bundled models added:
  - `kimi-k2.6:cloud`
  - `minimax-m2.5:cloud`
- model-aware bundled policy layer added in backend:
  - request rate limits by model
  - spend caps by model
- bundled cost simulation script added

This is code-ready for a hosted backend push.

## What Still Has To Be True Before Hosted Testing

### 1. Hosted backend env vars must be set

Required in the hosted `ite-cloud-api` environment:

```env
BUNDLED_PROVIDER_MODE=openrouter
OPENROUTER_BUNDLED_API_KEY=sk-or-...
OPENROUTER_BUNDLED_BASE_URL=https://openrouter.ai/api/v1

OPENROUTER_MODEL_KIMI=moonshotai/kimi-k2.5
OPENROUTER_MODEL_KIMI_2_6=moonshotai/kimi-k2.6
OPENROUTER_MODEL_MINIMAX_2_5=minimax/minimax-m2.5
OPENROUTER_MODEL_MINIMAX=minimax/minimax-m2.7
OPENROUTER_MODEL_GLM=z-ai/glm-5
OPENROUTER_MODEL_GLM_5_1=z-ai/glm-5.1
```

Still required as usual:

- `BETTER_AUTH_SECRET`
- `BETTER_AUTH_URL`
- `WEB_ORIGIN`
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- billing env vars if billing is live in that environment

### 2. A test account must have bundled entitlements

Bundled requests still require:

- `entitlements.bundledInference = true`

Current note:

- there is a backend route for this at `POST /billing/bundled-access`
- there is not yet a visible web control wired for flipping this in the account UI

So for hosted testing, you need either:

- a real subscribed account that already gets bundled access
- or a manual call to the backend toggle route while authenticated in the browser

### 3. Hosted web must point to the hosted backend

The hosted frontend must still be configured to use the same cloud API origin that has:

- the OpenRouter bundled key
- the entitlement state for the test user

## Push Readiness Checklist

Before pushing the backend:

1. Confirm hosted env vars are prepared.
2. Confirm the OpenRouter bundled key has enough spend headroom.
3. Confirm at least one browser account can be granted bundled access.
4. Confirm the hosted frontend is using the intended hosted API origin.

Before pushing runtime changes for end-to-end testing:

1. Confirm the runtime build you are testing points at the hosted cloud API.
2. Confirm `/cloud login` completes against the hosted backend.
3. Confirm the hosted backend returns bundled models from `/models/bundled`.

## Hosted End-to-End Test Plan

This test plan assumes:

- hosted `ite-cloud-api` is live
- hosted `ite-cloud-web` is live
- at least one test account has bundled access
- runtime build includes the latest changes

### A. Backend Smoke Check

Goal:

- verify the hosted backend is actually configured for bundled OpenRouter mode

Check:

1. Sign in on hosted web.
2. Verify the test account is valid.
3. Hit `GET /models/bundled` through an authenticated session.

Expected:

- `providerMode = "openrouter"`
- `providerAvailable = true`
- models include:
  - `kimi-k2.5:cloud`
  - `kimi-k2.6:cloud`
  - `minimax-m2.5:cloud`
  - `minimax-m2.7:cloud`
  - `glm-5:cloud`
  - `glm-5.1:cloud`
- every bundled entry should report `provider = "Bundled"`

If this fails:

- check hosted `OPENROUTER_BUNDLED_API_KEY`
- check hosted `BUNDLED_PROVIDER_MODE`
- check that the backend deploy actually contains the new code

### B. Hosted Web Check

Goal:

- verify hosted web copy matches the product state

Check pages:

- Billing page
- Settings page
- Docs page
- Activity page

Expected:

- bundled access is described as live, not “coming soon”
- BYOK is still described as a parallel option
- activity labels show the new model names correctly when data exists

### C. Runtime Bundled Path

Goal:

- verify terminal runtime uses hosted bundled inference

Steps:

1. Launch `ite`.
2. Run `/cloud login`.
3. Open the model picker.
4. Verify bundled entries appear as `Bundled`.
5. Select each bundled model one-by-one across separate prompts:
   - `minimax-m2.5:cloud`
   - `minimax-m2.7:cloud`
   - `kimi-k2.5:cloud`
   - `kimi-k2.6:cloud`
   - `glm-5:cloud`
   - `glm-5.1:cloud`

Expected:

- requests succeed through hosted backend
- `/usage` and `/activity` update
- model picker shows distinct `Bundled` labeling

### D. Runtime BYOK Path

Goal:

- verify Phase 1 did not break BYOK

Steps:

1. Run `/setup`.
2. Configure BYOK OpenRouter or another supported provider.
3. Send prompts successfully.
4. Return to the picker and confirm bundled entries still exist.

Expected:

- BYOK requests bypass bundled routing
- bundled and BYOK can coexist in the picker

### E. Same-Name Collision Case

Goal:

- verify same-name bundled and BYOK entries remain distinct

Steps:

1. Save a BYOK provider profile whose `model_name` matches a bundled model.
2. Open the model picker.

Expected:

- bundled entry shows source `Bundled`
- BYOK entry shows source `OpenRouter` or the custom provider label
- selecting bundled clears provider credentials
- selecting BYOK restores provider credentials

### F. Model Policy Enforcement

Goal:

- verify model-aware throttling works

Test cases:

1. Make repeated rapid requests to a stricter model like `kimi-k2.6:cloud`
2. Verify the backend returns:
   - `model_rate_limited`
   - or `model_budget_exhausted`

Expected runtime behavior:

- user sees a model-specific bundled error
- if a saved BYOK fallback exists, runtime may switch to it

### G. Usage Analytics

Goal:

- verify spend and activity reflect bundled usage

Check:

- hosted web Activity page
- hosted web Billing page
- runtime `/usage`
- runtime `/activity`

Expected:

- bundled spend increments
- by-model activity shows the chosen model
- model names display correctly for the new entries

### H. Mobile Remote

Goal:

- verify remote reflects hosted runtime state

Steps:

1. Connect `ite_remote` to a runtime session using a bundled model.
2. Send prompts through the host session.

Expected:

- remote continues to function normally
- active model/session state reflects the host
- no mobile-specific routing changes are required

## Hosted Rollback Plan

If hosted bundled OpenRouter mode misbehaves:

1. set `BUNDLED_PROVIDER_MODE=direct` or `ollama` if that fallback path is still valid for your environment
2. or disable bundled access for test accounts
3. or remove the hosted bundled key and let `/models/bundled` report unavailable

The safest rollback is entitlement-based:

- keep deploy live
- disable `bundledInference` for test accounts

## Budget And Cost Analysis Workflow

Use the backend simulator before and after hosted rollout:

```bash
npm run build
node dist/scripts/cost-sim.js --users 50 --active-user-ratio 0.4 --active-days 18 --retry-multiplier 1.08 --usd-to-ngn 1367
```

Recommended workflow:

1. simulate with planned assumptions
2. run hosted beta with a small real user cohort
3. compare actual `usage_events` against the simulated model mix
4. adjust per-model policy caps in `ite-cloud-api/src/lib/usage.ts`

## Important Known Gap

There is still no dedicated hosted admin UI control for flipping bundled access on a user account.

So for now, end-to-end hosted testing depends on either:

- a real bundled-entitled account
- or a manual backend toggle path

## Recommended First Hosted Test Sequence

1. Deploy backend with hosted OpenRouter env vars set.
2. Deploy web.
3. Verify `/models/bundled` returns `openrouter` mode and `providerAvailable = true`.
4. Enable bundled access for one internal test account.
5. Run runtime hosted test with:
   - `minimax-m2.5:cloud`
   - `kimi-k2.6:cloud`
6. Confirm Activity and Billing update.
7. Test BYOK still works.
8. Test one rate-limit path intentionally.

That is the cleanest hosted Phase 1 acceptance path.
