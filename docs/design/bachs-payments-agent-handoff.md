# Bachs Payments Agent Handoff

## Purpose

This document is a fresh-context handoff for future agent sessions working on iTE's Bachs payments integration. It summarizes what changed, why it changed, the current architecture, expected behavior, environment setup, test strategy, and known constraints.

## High-Level Decision

iTE previously used Polar for subscription checkout, subscription webhooks, trial status, and customer portal behavior. The current migration replaces Polar with Bachs.

The public Bachs API currently supports hosted checkout sessions and payment collection webhooks. It does not publicly expose a complete Polar-equivalent subscription trial and auto-renewal API. Because of that, iTE now models Pro access as local 30-day access grants created from Bachs checkout success events.

The product model is:

- `ite_pro_trial`: one free 30-day Pro access grant through a `$0` Bachs product.
- `ite_pro_monthly`: renewable paid 30-day Pro access through an `$8` Bachs product.

There is no automatic renewal and no customer subscription portal. After a trial or paid pass expires, the user must manually start another paid checkout.

## Repositories And Surfaces

The work spans three local workspaces under `/Users/kiishidavid/Documents/Dev/Projects/ite`:

- `ite-cloud-api/`: Fastify TypeScript backend. Owns Bachs API calls, billing routes, DB state, webhook validation, and entitlement grants.
- `ite-cloud-web/`: React/Vite frontend. Owns pricing and account billing UI.
- root `ite/`: Python iTE runtime. Only minor runtime-facing activity copy was changed.

## Key Backend Files

- `ite-cloud-api/src/lib/bachs.ts`
  - Bachs provider/client helper.
  - Exports `PLAN_KEYS`, pricing catalog, product lookup, plan resolution, signature validation, access grant construction, and checkout creation.
  - Makes direct `fetch` calls to Bachs instead of using an SDK.

- `ite-cloud-api/src/routes/billing.ts`
  - Registers `/pricing/catalog`, `/billing/checkout`, `/billing/webhooks/bachs`, `/billing/me`, `/billing/bundled-access`, `/billing/sync`, and a stub `/billing/portal`.
  - Creates Bachs checkout sessions.
  - Reserves trial checkout attempts to enforce one free month per app user.
  - Processes `collection.succeeded` webhooks and grants local Pro access.
  - Recomputes entitlement state from local active access records during `/billing/sync`.

- `ite-cloud-api/src/db/database.ts`
  - Adds provider-neutral columns while leaving older Polar columns in place for deployment compatibility.
  - Adds `trial_started_at` and `trial_used_at` on `billing_customers`.

- `ite-cloud-api/src/lib/contracts.ts`
  - `createCheckoutRequestSchema` allows `ite_pro_trial` and `ite_pro_monthly`.

- `ite-cloud-api/src/lib/config.ts`
  - Uses `BACHS_*` env vars, not `POLAR_*`.

- `ite-cloud-api/tests/bachs.test.ts`
  - Node test runner tests for Bachs signature validation, access grant behavior, and trial-plan helpers.

## Key Frontend Files

- `ite-cloud-web/src/lib/api.ts`
  - Pricing catalog type includes `provider: "bachs"`, `trialOffer`, and `accessPass`.
  - `createCheckout` accepts `ite_pro_trial` or `ite_pro_monthly`.
  - `billingMe` and `syncBilling` include trial state.

- `ite-cloud-web/src/pages/PricingPage.tsx`
  - Public pricing now shows first month free, then `$8` renewable 30-day access passes.
  - Signed-out CTA preserves `checkout=ite_pro_trial` through login.
  - Signed-in free users with trial available start trial checkout.
  - Users whose trial is no longer available start paid checkout.
  - Pro users are routed to account billing.

- `ite-cloud-web/src/pages/BillingPage.tsx`
  - Shows trial-active copy when entitlement plan key is `ite_pro_trial`.
  - Shows “Start free month” when trial is available.
  - Shows “Buy 30 days of Pro” when trial is no longer available.
  - Does not show subscription portal/manage-subscription controls.

## Runtime File

- `src/ite/ui/reup/modals.py`
  - Activity label maps `billing.access_granted` to “Pro access granted”.

## Environment Variables

Required Bachs variables for billing to be configured:

```bash
BACHS_API_KEY=sk_sandbox_... or sk_live_...
BACHS_WEBHOOK_SECRET=...
BACHS_SERVER=sandbox # or production
BACHS_PRODUCT_ID_ITE_PRO_TRIAL=prod_...
BACHS_PRODUCT_ID_ITE_PRO_MONTHLY=prod_...
```

Important non-Bachs cloud variables still needed:

```bash
WEB_ORIGIN=https://your-web-domain
BETTER_AUTH_URL=https://your-api-domain
BETTER_AUTH_SECRET=...
TURSO_DATABASE_URL=...
TURSO_AUTH_TOKEN=...
OPENROUTER_BUNDLED_API_KEY=...
```

Old Polar variables should not be used:

```bash
POLAR_ACCESS_TOKEN
POLAR_WEBHOOK_SECRET
POLAR_SERVER
POLAR_PRODUCT_ID_ITE_PRO_MONTHLY
```

## Bachs Dashboard Setup

Create two one-time Bachs products:

1. `iTE Pro Trial`
   - Amount: `$0`
   - Product ID goes into `BACHS_PRODUCT_ID_ITE_PRO_TRIAL`

2. `iTE Pro 30 Days`
   - Amount: `$8`
   - Product ID goes into `BACHS_PRODUCT_ID_ITE_PRO_MONTHLY`

Create a webhook endpoint:

```text
https://YOUR_API_DOMAIN/billing/webhooks/bachs
```

Subscribe at least to:

- `collection.succeeded`
- `collection.failed`
- `collection.abandoned`
- `collection.underpaid`

Only `collection.succeeded` grants Pro access. Other events are stored in `billing_events` but do not grant access.

## API Key Scopes

For the current code, use least privilege:

- Payments: Write
- Everything else: No Access

The backend only calls `POST /v1/checkout-sessions`. It does not read customers, products, refunds, payouts, or webhooks through the API. Webhook validation is local using `BACHS_WEBHOOK_SECRET`.

If Bachs requires read permission for checkout creation or future status polling, add Payments: Read later.

## Checkout Flow

Frontend calls:

```http
POST /billing/checkout
```

Body:

```json
{
  "planKey": "ite_pro_trial",
  "successUrl": "https://web/account/billing?checkout=success",
  "returnUrl": "https://web/pricing"
}
```

or:

```json
{
  "planKey": "ite_pro_monthly"
}
```

Backend behavior:

1. Requires browser session.
2. Validates Bachs config.
3. Resolves plan key to product ID.
4. For `ite_pro_trial`, checks `billing_customers.trial_started_at` and `trial_used_at`.
5. If the trial has not started or been used, reserves the trial by setting `trial_started_at`.
6. Calls Bachs `POST /v1/checkout-sessions`.
7. Sends metadata:

```json
{
  "user_id": "app user id",
  "plan_key": "ite_pro_trial or ite_pro_monthly",
  "product_id": "Bachs product id"
}
```

8. Returns `checkoutId` and `checkoutUrl`.

If Bachs checkout creation fails for a trial before redirect, the reservation is cleared so the user can retry.

## Webhook Flow

Bachs posts to:

```text
POST /billing/webhooks/bachs
```

The API verifies:

- `X-Bachs-Timestamp`
- `X-Bachs-Signature`
- HMAC SHA256 over `timestamp + "." + rawBody`

Webhook idempotency:

- Uses webhook envelope `id`.
- Stores it in `billing_events.event_id`.
- If already seen, returns `{ ok: true }`.

For `collection.succeeded`:

1. Reads `metadata.user_id`.
2. Reads `metadata.product_id` or falls back to configured monthly product.
3. Resolves plan key from metadata/product.
4. Builds a 30-day access grant.
5. Upserts a row into `subscriptions` with `status = active`.
6. Upserts `entitlements` with `bundled_inference = 1` and `pro_access = 1`.
7. If plan is `ite_pro_trial`, sets `billing_customers.trial_used_at`.
8. Logs `billing.access_granted`.

Important: If Bachs does not echo checkout metadata in `collection.succeeded`, access cannot be granted to the right user. In that case, add a local checkout mapping table keyed by `checkout_id`.

## Database Model

Important tables:

- `billing_customers`
  - `user_id`
  - `billing_provider`
  - `provider_customer_id`
  - legacy compatibility columns: `polar_customer_id`, `polar_external_customer_id`
  - `email`
  - `trial_started_at`
  - `trial_used_at`
  - timestamps

- `subscriptions`
  - Still named `subscriptions` for compatibility, but now represents local access grants.
  - `id` is charge id, checkout id, or generated UUID.
  - `billing_provider = 'bachs'`
  - provider-neutral columns: `provider_customer_id`, `provider_product_id`, `provider_checkout_id`, `provider_charge_id`
  - legacy compatibility columns: `polar_customer_id`, `polar_product_id`
  - `plan_key`
  - `status`
  - `current_period_start`
  - `current_period_end`
  - timestamps

- `entitlements`
  - Source of truth for runtime access checks.
  - `pro_access = 1` and `bundled_inference = 1` means Pro access is active.

- `billing_events`
  - Stores webhook events idempotently.

## Trial Guardrail

The trial is one per app user.

The API blocks trial checkout if either of these exists:

- `billing_customers.trial_started_at`
- `billing_customers.trial_used_at`

This deliberately prevents repeated `$0` checkouts. If a user starts a trial checkout and abandons it, they may be blocked from retrying unless support clears `trial_started_at`. This is conservative fraud prevention. If a smoother UX is desired later, add trial checkout expiry handling or clear `trial_started_at` on `collection.abandoned`.

## Sync Behavior

`POST /billing/sync` does not call Bachs. It recomputes local entitlements from local active Bachs access records:

- If active, unexpired access exists, Pro entitlement remains enabled.
- If not, `markFreeEntitlements()` downgrades the user to Free.

This means the webhook is the primary activation path.

## Known Constraints

- No automatic renewal.
- No customer portal.
- No Bachs subscription cancellation flow.
- No card-upfront trial.
- No provider-side entitlement lookup.
- Webhook metadata is essential unless a checkout mapping table is added.
- Trial reservation currently blocks retries after a successful checkout-start even if the user abandons checkout.

## Verification Commands

Run in `ite-cloud-api`:

```bash
npm test
npm run typecheck
npm run build
```

Run in `ite-cloud-web`:

```bash
npm run build
```

Run in root runtime repo:

```bash
uv run --with pytest pytest tests/test_llm_client.py
```

## Hosted End-To-End Test Plan

After deploying API and web:

1. Confirm API health:

```http
GET https://YOUR_API_DOMAIN/health
```

2. Confirm catalog:

```http
GET https://YOUR_API_DOMAIN/pricing/catalog
```

Expected:

- `provider: "bachs"`
- `billingConfigured: true`
- `trialOffer.planKey: "ite_pro_trial"`
- `trialOffer.label: "First month free"`
- `accessPass.label: "30 days of Pro access"`

3. Open web `/pricing` signed out.

Expected:

- Shows first month free.
- CTA says “Start free month”.

4. Click CTA signed out.

Expected:

- User is sent to sign-up/login.
- After auth, checkout starts automatically.
- Checkout should be for the `$0` Bachs trial product.

5. Complete Bachs sandbox checkout.

Expected:

- Redirect back to `/account/billing?checkout=success`.
- Bachs sends `collection.succeeded`.
- API logs do not show invalid signature.
- Account billing eventually shows Pro active / free month active.

6. Verify API state:

```http
GET https://YOUR_API_DOMAIN/billing/me
```

Expected:

- `entitlements.proAccess: true`
- `entitlements.bundledInference: true`
- `entitlements.planKey: "ite_pro_trial"`
- `trial.startedAt` is not null.
- `trial.usedAt` is not null after webhook success.
- `subscription.currentPeriodEnd` is roughly 30 days after webhook processing.

7. Try starting a trial again after logging out/in or visiting pricing.

Expected:

- UI should offer paid checkout if trial is unavailable.
- Direct API `POST /billing/checkout` with `ite_pro_trial` should return conflict.

8. Complete paid checkout.

Use an account whose trial is used/unavailable, or force `checkout=ite_pro_monthly`.

Expected:

- Checkout should be for the `$8` product.
- Webhook success grants another 30-day active access record.
- `entitlements.planKey` becomes `ite_pro_monthly` if the paid grant is the latest active grant.

9. Runtime usage test.

In iTE runtime, sign in with the same user and call a bundled model.

Expected:

- Entitlement check passes.
- Inference call succeeds.
- Usage appears on account activity/billing.

10. Negative webhook test.

Send/replay a webhook with wrong signing secret or configure wrong `BACHS_WEBHOOK_SECRET`.

Expected:

- API rejects it.
- No Pro entitlement is granted.

## Future Improvements

- Add a `billing_checkouts` table keyed by `checkout_id` to avoid relying entirely on Bachs metadata.
- Clear `trial_started_at` on `collection.abandoned` after validating webhook metadata.
- Add admin/support tooling to clear a stuck trial reservation.
- Rename `subscriptions` to `billing_access_grants` once legacy compatibility is no longer needed.
- Add integration tests around Fastify route injection with mocked Bachs fetch and mocked auth.
- Add a paid renewal flow from BillingPage for active trial users before trial expiry.
