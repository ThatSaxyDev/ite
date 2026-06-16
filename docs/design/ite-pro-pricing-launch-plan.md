# iTE Pro Pricing Launch Plan

## Summary

Launch iTE Pro with one public paid plan:

**First month free, then $8 for each 30-day Pro access pass.**

Use Bachs hosted checkout sessions and payment webhooks. The free month is modeled as a separate `$0` Bachs product and the paid month is modeled as a separate `$8` Bachs product. The launch scope is public pricing UI, signed-out-to-checkout flow, Bachs checkout, authenticated billing polish, runtime messaging, and tests. Do not build or expose credit/top-up functionality in this pass.

## Product Decision

- Product name: iTE Pro
- Internal plan keys: `ite_pro_trial`, `ite_pro_monthly`
- Public offer: first month free, then $8 for 30 days of Pro access
- Billing provider: Bachs
- Trial mechanism: Bachs-backed `$0` checkout product, one per app user
- Discount mechanism: not used for launch
- Credit/top-up ledger: out of scope

## Backend Work

Add an API-backed pricing catalog/config that returns:

- `planKey: "ite_pro_monthly"`
- display name: `iTE Pro`
- trial offer: `ite_pro_trial`, first month free
- access pass: 30 days
- recurring price: `$8/month`
- billing provider/configured state
- summarized rolling fair-use limits
- model-based request estimates for 5-hour, weekly, and monthly windows

Update checkout creation so `ite_pro_trial` and `ite_pro_monthly` create Bachs checkout sessions with:

- product: configured iTE Pro Bachs trial or monthly product id
- customer email/name
- return URL: account billing success state
- cancel URL: account billing or pricing
- metadata: app user id and plan key

For `ite_pro_trial`, reserve the trial before checkout and block future trial attempts for the same app user. If Bachs checkout creation fails before redirect, clear the reservation.

Keep entitlement behavior:

- `collection.succeeded` grants 30 days of Pro access
- trial success marks `trial_used_at`
- expired local access downgrades to free during billing sync

Do not add `discount_id`.

## Web Work

Add public `/pricing` outside auth.

Pricing page should show:

- iTE Pro
- first month free
- 30 days of Pro access
- $8/month
- bundled models included within rolling 5-hour, weekly, and monthly fair-use windows
- model-based request estimates instead of public dollar cap labels
- local models and BYOK remain available
- renew month to month
- clear CTA

Landing page:

- Add “Pricing” glitch text link.
- Desktop: top-center placement.
- Mobile: place cleanly without competing with install/sign-in actions.

CTA behavior:

- signed out: go to login/signup with checkout intent, then start checkout after auth
- signed in and free with trial available: start Bachs trial checkout immediately
- signed in and free after trial started/used: start Bachs paid checkout immediately
- signed in and active: route to `/account/billing`

Account billing:

- Replace generic “Pro” copy with precise iTE Pro copy.
- Show trial-active state when the active grant came from `ite_pro_trial`.
- Show access end date clearly.
- Show first-month-free or `$8/month` as appropriate.
- Keep refresh usage action.

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

- pricing catalog returns iTE Pro, trial offer, 30-day access, and `$8/month`
- checkout creates Bachs session for `ite_pro_trial`
- checkout creates Bachs session for `ite_pro_monthly`
- duplicate trial checkout for the same app user is blocked
- webhook maps trial `collection.succeeded` to Pro entitlements and marks trial used
- webhook maps paid `collection.succeeded` to Pro entitlements
- expired local access downgrades to free
- quota enforcement still blocks over-limit Pro users
- monthly quota enforcement blocks over-limit Pro users

Web:

- `/pricing` renders public trial and access-pass pricing copy
- landing Pricing link appears correctly on desktop and mobile
- signed-out CTA preserves checkout intent through auth
- signed-in free user starts checkout
- active user routes to account billing

Runtime:

- entitlement-denied message points to pricing
- quota-exhausted message points to billing/usage management
- BYOK/local fallback message remains available

## Assumptions

- iTE Pro is the only paid launch plan.
- Bachs trial product base price is configured as `$0`.
- Bachs monthly product base price is configured as `$8/month`.
- Automatic renewal is not implemented because public Bachs subscription trial APIs are not available.
- No credit ledger, top-ups, metered billing, or public overage controls ship in this pass.
- Public pricing does not show raw internal dollar caps; account usage may show remaining quota by window.
