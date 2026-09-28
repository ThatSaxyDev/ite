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
  - `moonshotai/kimi-k2.6`
  - `minimax/minimax-m2.5`
- model-aware bundled policy layer added in backend:
  - request rate limits by model
  - spend caps by model
- bundled cost simulation script added
- temporary admin API controls added for hosted testing:
  - usage reset by scope
  - usage session simulation by user

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
ADMIN_EMAILS=real-admin-account@example.com
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
- there is not yet a dedicated admin panel for billing/usage operator controls

So for hosted testing, you need either:

- a real subscribed account that already gets bundled access
- or a manual call to the backend toggle route while authenticated in the browser

### 3. Hosted web must point to the hosted backend

The hosted frontend must still be configured to use the same cloud API origin that has:

- the OpenRouter bundled key
- the entitlement state for the test user

### 4. Operator workflows are currently API-first

Until there is a dedicated admin panel, operator tasks are done through backend routes from a signed-in browser session:

- `POST /admin/usage/simulate`
- `POST /admin/usage/reset`
- `GET /admin/usage/resets`

These routes require:

- a real browser account that can sign in
- that account's email to be listed in `ADMIN_EMAILS`

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
  - `moonshotai/kimi-k2.5`
  - `moonshotai/kimi-k2.6`
  - `minimax/minimax-m2.5`
  - `minimax/minimax-m2.7`
  - `z-ai/glm-5`
  - `z-ai/glm-5.1`
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
   - `minimax/minimax-m2.5`
   - `minimax/minimax-m2.7`
   - `moonshotai/kimi-k2.5`
   - `moonshotai/kimi-k2.6`
   - `z-ai/glm-5`
   - `z-ai/glm-5.1`

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

1. Make repeated rapid requests to a stricter model like `moonshotai/kimi-k2.6`
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

## Temporary Operator Workflow

This is the current way to test realistic usage without manually sending prompts through the runtime.

### A. Create or choose a real browser admin account

Requirements:

- the account must be able to sign in normally on hosted web
- its email must be listed in `ADMIN_EMAILS`

Example:

```env
ADMIN_EMAILS=you@example.com
```

### B. Create the target test user normally

Create the target account through the real web auth flow.

Example target:

- `daviddedeke10@gmail.com`

### C. Simulate a bundled work session

While signed in on hosted web as the admin account, open the browser console and run:

```js
await fetch("https://ite-cloud-api.onrender.com/admin/usage/simulate", {
  method: "POST",
  credentials: "include",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    targetEmail: "daviddedeke10@gmail.com",
    profile: "power_user",
    startedMinutesAgo: 90
  })
}).then(async (r) => ({ status: r.status, body: await r.json() }))
```

What this does:

- targets one real user by email
- seeds a realistic bundled session directly into `usage_events`
- updates Usage and Billing through the normal API accounting path

This does **not** call OpenRouter. It simulates the accounting side of a bundled session.

### D. Available session profiles

#### `typical_paid`

Represents a normal paid session:

- around 6 requests
- prompt sizes roughly `11k` to `16k`
- mixed bundled models
- good baseline for ordinary usage

#### `power_user`

Represents a user actively leaning on the product:

- around 10 requests
- prompt sizes roughly `12k` to `26k`
- sustained work over roughly 2.5 hours
- recommended default profile for hosted testing

#### `quota_edge`

Represents a session designed to get close to rolling limits:

- around 12 requests
- heavier prompts
- useful for checking usage windows and model policy responses

#### `budget_stress`

Represents deliberately expensive usage:

- emphasizes `kimi-k2.6` and other pricier models
- prompt sizes roughly `24k` to `50k`
- useful for stress-testing spend behavior

### E. Reset usage limits after testing

To reset one user:

```js
await fetch("https://ite-cloud-api.onrender.com/admin/usage/reset", {
  method: "POST",
  credentials: "include",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    scope: "users",
    userIds: ["<target-user-id>"],
    reason: "Reset after hosted usage test"
  })
}).then(async (r) => ({ status: r.status, body: await r.json() }))
```

To reset everyone:

```js
await fetch("https://ite-cloud-api.onrender.com/admin/usage/reset", {
  method: "POST",
  credentials: "include",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    scope: "all",
    reason: "Global usage reset after hosted QA"
  })
}).then(async (r) => ({ status: r.status, body: await r.json() }))
```

Important:

- resets affect usage-limit calculations
- resets do **not** erase billing/activity history
- Billing analytics remain a ledger view of what happened
- Usage windows begin counting again from the reset cutoff

### F. What to verify after simulation

After seeding a session:

1. open the target user's Usage page
2. verify 5-hour and weekly windows show non-zero usage
3. open the target user's Billing page
4. verify daily spend, model breakdown, and totals match the simulated session
5. verify free models, if included, show requests but `$0.00`

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
   - `minimax/minimax-m2.5`
   - `moonshotai/kimi-k2.6`
6. Confirm Activity and Billing update.
7. Test BYOK still works.
8. Test one rate-limit path intentionally.

That is the cleanest hosted Phase 1 acceptance path.
