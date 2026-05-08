# iTE Pro Pricing Launch Plan

## Summary

Launch iTE Pro with one public paid plan:

**First month free, then $8/month.**

Use Polar subscription trials, not discounts. The launch scope is public pricing UI, signed-out-to-checkout flow, Polar trial checkout, authenticated billing polish, runtime messaging, and tests. Do not build or expose credit/top-up functionality in this pass.

## Product Decision

- Product name: iTE Pro
- Internal plan key: `ite_pro_monthly`
- Public offer: first month free, then $8/month
- Billing provider: Polar
- Trial mechanism: Polar trial support
- Discount mechanism: not used for launch
- Credit/top-up ledger: out of scope

## Backend Work

Add an API-backed pricing catalog/config that returns:

- `planKey: "ite_pro_monthly"`
- display name: `iTE Pro`
- trial: one month free
- recurring price: `$8/month`
- billing provider/configured state
- summarized rolling fair-use limits
- model-based request estimates for 5-hour, weekly, and monthly windows

Update checkout creation so `ite_pro_monthly` creates a Polar checkout session with:

- product: configured iTE Pro Polar product id
- trial interval: `month`
- trial interval count: `1`
- external customer id: app user id
- customer email/name
- success URL: account billing success state
- return URL: account billing or pricing

Keep entitlement behavior:

- `trialing` grants Pro access
- `active` grants Pro access
- canceled/inactive/past-due revoked states downgrade to free according to current billing rules

Do not add `discount_id`.

## Web Work

Add public `/pricing` outside auth.

Pricing page should show:

- iTE Pro
- first month free
- then $8/month
- bundled models included within rolling 5-hour, weekly, and monthly fair-use windows
- model-based request estimates instead of public dollar cap labels
- local models and BYOK remain available
- cancel anytime
- clear CTA

Landing page:

- Add “Pricing” glitch text link.
- Desktop: top-center placement.
- Mobile: place cleanly without competing with install/sign-in actions.

CTA behavior:

- signed out: go to login/signup with checkout intent, then start checkout after auth
- signed in and free: start Polar checkout immediately
- signed in and trialing/active: route to `/account/billing`

Account billing:

- Replace generic “Pro” copy with precise iTE Pro copy.
- Show trial/renewal state clearly.
- Show `$8/month after trial`.
- Keep manage subscription and refresh usage actions.

## Runtime Work

Update bundled model error copy:

- entitlement denied: point users to `/pricing`
- quota exhausted: point users to account billing/usage management
- keep BYOK/local fallback guidance

Enforce quota across global rolling 5-hour, weekly, and monthly windows. Keep
model-specific request-rate limits for burst control, but do not expose or rely
on separate per-model spend caps as the public product model.

## Tests

Backend:

- pricing catalog returns iTE Pro, one-month trial, and `$8/month`
- checkout creates Polar session for `ite_pro_monthly` with trial fields
- webhook/sync maps `trialing` to Pro entitlements
- webhook/sync maps `active` to Pro entitlements
- canceled/inactive subscription downgrades to free
- quota enforcement still blocks over-limit Pro users
- monthly quota enforcement blocks over-limit Pro users

Web:

- `/pricing` renders public trial and pricing copy
- landing Pricing link appears correctly on desktop and mobile
- signed-out CTA preserves checkout intent through auth
- signed-in free user starts checkout
- trialing/active user routes to account billing

Runtime:

- entitlement-denied message points to pricing
- quota-exhausted message points to billing/usage management
- BYOK/local fallback message remains available

## Assumptions

- iTE Pro is the only paid launch plan.
- Polar product base price is configured as `$8/month`.
- Trial is implemented with Polar trial fields, not discounts.
- No credit ledger, top-ups, metered billing, or public overage controls ship in this pass.
- Public pricing does not show raw internal dollar caps; account usage may show remaining quota by window.
