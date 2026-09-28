# OpenRouter Bundled Usage, Phase 1

## Goal

Ship bundled models through iTE Cloud without removing BYOK.

Phase 1 should let iTE offer managed access to bundled models while preserving:

- local Ollama usage
- OpenRouter BYOK usage
- other OpenAI-compatible BYOK providers

This document reflects the current repo state across:

- `src/ite/` runtime app
- `ite-cloud-api/` backend
- `ite-cloud-web/` account and billing web app
- `ite_remote/` mobile remote app

## Product Direction

The recommended Phase 1 path is:

- keep BYOK as a first-class option
- keep bundled usage behind iTE Cloud auth and entitlements
- fulfill bundled requests through a single backend OpenRouter account
- do not expose the bundled provider key to clients

OpenRouter should be the backend provider for bundled usage in Phase 1, not the client-side setup path for bundled usage.

Users can still use OpenRouter in `/setup` for BYOK with their own key.

## Important Clarification

The `:cloud` suffix in model names is not a valid product-level criterion for bundled vs BYOK.

In this repo, names like `kimi-k2.5:cloud` and `minimax-m2.7:cloud` came from the earlier Ollama/cloud naming path. They should be treated as model names, not as the deciding signal for routing.

The current repo already has better differentiators than a model-name suffix.

## Existing Differentiators Already In The Code

### 1. Bundled entitlement

Bundled access is already represented in backend entitlements:

- `entitlements.bundledInference`

Relevant code:

- `ite-cloud-api/src/routes/billing.ts`
- `ite-cloud-api/src/routes/inference.ts`
- `ite-cloud-api/src/routes/models.ts`

### 2. Bundled model catalog

Bundled models already come from the backend model catalog:

- `GET /models/bundled`

Relevant code:

- `ite-cloud-api/src/routes/models.ts`
- `src/ite/cloud/auth.py`

### 3. Saved BYOK profiles

Saved user-managed providers already exist and are keyed by model name in:

- `saved_custom_providers`

Relevant code:

- `src/ite/config/loader.py`

### 4. BYOK provider inference

The setup flow already distinguishes:

- `ollama`
- `openrouter`
- generic OpenAI-compatible providers

Relevant code:

- `src/ite/ui/reup/modals.py`

### 5. Backend bundled provider mode

The backend already has a bundled provider switch:

- `BUNDLED_PROVIDER_MODE`

Relevant code:

- `ite-cloud-api/src/lib/config.ts`

## Current State By Surface

### Runtime app (`src/ite/`)

What already exists:

- cloud auth and bundled session flow
- bundled inference path through `ite-cloud-api`
- saved BYOK/custom provider profiles
- model picker showing bundled models and saved BYOK entries together
- usage UI for bundled spend windows

What is currently wrong:

- `LLMClient._is_cloud_model()` still uses `model_name.endswith(":cloud")` as part of its bundled routing decision
- this is a naming leak from the older setup and should not be the routing criterion

Relevant files:

- `src/ite/client/llm_client.py`
- `src/ite/ui/reup/app.py`
- `src/ite/ui/reup/modals.py`
- `src/ite/cloud/auth.py`

### Backend (`ite-cloud-api/`)

What already exists:

- bundled entitlement enforcement
- usage quota windows
- activity logging
- billing integration
- fixed bundled model catalog
- provider routing for bundled inference

What is currently wrong for Phase 1:

- bundled routing is still split between:
  - `ollama`
  - `direct` provider keys for Kimi / MiniMax / GLM
- there is no explicit `openrouter` bundled mode yet
- bundled pricing is hardcoded against direct provider model definitions

Relevant files:

- `ite-cloud-api/src/routes/inference.ts`
- `ite-cloud-api/src/lib/usage.ts`
- `ite-cloud-api/src/lib/config.ts`
- `ite-cloud-api/src/routes/models.ts`
- `ite-cloud-api/src/routes/usage.ts`

### Web (`ite-cloud-web/`)

What already exists:

- billing page for bundled access
- usage summary page
- activity analytics
- onboarding/settings guidance for BYOK

What is stale:

- docs and onboarding copy still partially frame bundled access as future/coming soon
- bundled product language should be updated to reflect the actual managed offering

Relevant files:

- `ite-cloud-web/src/pages/BillingPage.tsx`
- `ite-cloud-web/src/pages/ActivityPage.tsx`
- `ite-cloud-web/src/pages/SettingsPage.tsx`
- `ite-cloud-web/src/pages/DocsPage.tsx`

### Mobile remote (`ite_remote/`)

The mobile app is not a bundled-provider surface.

It reflects runtime state coming from the host session, including the selected model label, but it does not decide bundled vs BYOK routing.

Relevant files:

- `ite_remote/lib/remote/models/remote_models.dart`

## Main Conclusion

OpenRouter is the right Phase 1 backend provider for bundled usage.

This should be implemented as:

- runtime clients talk to iTE Cloud
- iTE Cloud talks to OpenRouter using iTE-managed credentials
- BYOK continues to work independently through existing setup and saved provider flows

This avoids:

- maintaining separate direct provider billing and auth for MiniMax, GLM, and Kimi in Phase 1
- exposing provider keys to clients
- multiplying provider-specific operational work before bundled usage is proven

## Recommended Phase 1 Architecture

### Client behavior

The client should continue to support two broad paths:

- bundled usage through iTE Cloud
- BYOK/local usage through the existing direct provider path

The client should not decide bundled routing from a `:cloud` suffix.

Instead, the decision should come from the repo’s existing signals:

- bundled model availability from `/models/bundled`
- saved BYOK provider profiles
- active configured provider credentials

### Backend behavior

Add a bundled provider mode for OpenRouter:

- `BUNDLED_PROVIDER_MODE=openrouter`

Bundled inference should then:

1. validate entitlement
2. validate quota window
3. map bundled model ids to OpenRouter upstream model ids
4. send the request through the iTE-managed OpenRouter account
5. record usage and activity
6. return normalized output to the runtime

### Billing and usage behavior

Keep the existing usage model:

- rolling 5-hour cap
- rolling 7-day cap
- spend-based usage analytics
- entitlement-gated bundled access

That part of the product is already aligned with a managed bundled model offering.

## What Should Change

### 1. Stop using `:cloud` as the bundled routing criterion

Current issue:

- `src/ite/client/llm_client.py` still treats the suffix as part of the decision

Desired behavior:

- bundled vs BYOK should be decided from existing bundled catalog and provider state, not from model-name suffix parsing

### 2. Add explicit OpenRouter bundled mode on the backend

Current issue:

- backend bundled mode is effectively `ollama` or direct per-provider keys

Desired behavior:

- support `BUNDLED_PROVIDER_MODE=openrouter`

### 3. Route bundled models through OpenRouter-managed model ids

Current issue:

- bundled model definitions assume direct provider upstream ids and direct provider ownership

Desired behavior:

- keep user-facing bundled labels stable
- map them server-side to OpenRouter model ids

### 4. Update bundled cost definitions

Current issue:

- `ite-cloud-api/src/lib/usage.ts` prices bundled requests using direct-provider assumptions

Desired behavior:

- price against the actual OpenRouter-backed bundled offering for the chosen models

### 5. Fix model picker source labeling

Current issue:

- bundled entries can be shadowed by saved BYOK profiles with the same model name
- this can make the `Source` column show `Ollama` or `OpenRouter` when the product goal is to show the bundled source clearly

Desired behavior:

- bundled entries should render as `Bundled`, `iTE`, or another explicit in-house label
- BYOK entries should continue to show `Ollama`, `OpenRouter`, or the custom host/provider label
- same-name bundled and BYOK entries should not silently collapse in a way that mislabels bundled models

### 6. Refresh web copy

Current issue:

- some docs still describe bundled access as future work

Desired behavior:

- web copy should describe bundled access as an actual managed product path
- BYOK should be described as a parallel option, not a fallback-only option

## What Should Not Change In Phase 1

- do not remove BYOK
- do not remove local Ollama support
- do not move bundled routing into the desktop or mobile client
- do not expose the OpenRouter bundled key to end users
- do not require a full backend redesign before launching bundled access

## Suggested Model Source Language

For user-facing display in the model picker and related surfaces:

- bundled models: `Bundled`
- BYOK OpenRouter: `OpenRouter`
- BYOK local Ollama: `Ollama`
- other BYOK providers: provider host or `Custom provider`

`Bundled` is the clearest default label for Phase 1.

If branding later matters more, this can become:

- `iTE`
- `Managed by iTE`
- `In-house`

But `Bundled` is the least ambiguous starting point.

## Implementation Checklist

### Runtime

- replace suffix-based bundled routing in `LLMClient`
- use existing bundled catalog and saved-provider differentiators consistently
- fix model-picker source precedence and same-name conflicts

### Backend

- add `openrouter` bundled provider mode
- add OpenRouter bundled env vars
- map bundled model keys to OpenRouter upstream ids
- update cost assumptions
- keep entitlements, quotas, and analytics unchanged

### Web

- update docs and onboarding copy
- keep billing and activity flows as-is
- clarify bundled vs BYOK positioning

### Mobile remote

- no bundled architecture changes required
- only reflect improved runtime labels if they change

## Immediate Code Targets

These are the first files a new session should inspect if implementation starts from this document.

### Runtime

- `src/ite/client/llm_client.py`
  Current problem: bundled routing still depends in part on `model_name.endswith(":cloud")`.
  Goal: route bundled usage using the existing bundled and saved-provider differentiators already present in the repo.

- `src/ite/ui/reup/app.py`
  Current problem: the model picker merges saved BYOK profiles and bundled entries in a way that can make bundled entries inherit or appear under a BYOK-style source label.
  Goal: make bundled entries show a distinct source label such as `Bundled`, while keeping BYOK labels like `Ollama`, `OpenRouter`, or custom host names.

- `src/ite/ui/reup/modals.py`
  Current role: setup and model-selection UI logic already distinguishes Ollama, OpenRouter, and generic BYOK providers.
  Goal: keep using this distinction for BYOK, but do not let it blur bundled entries in the shared model list.

### Backend

- `ite-cloud-api/src/lib/config.ts`
  Current problem: bundled provider mode only covers the current direct/ollama-oriented setup.
  Goal: add an explicit OpenRouter-backed bundled mode and the related environment variables.

- `ite-cloud-api/src/routes/inference.ts`
  Current problem: bundled provider routing is still tied to the older direct-provider split.
  Goal: map bundled model keys to OpenRouter upstream model ids when bundled mode is backed by OpenRouter.

- `ite-cloud-api/src/lib/usage.ts`
  Current problem: bundled cost estimation is still expressed in terms of the current direct-provider assumptions.
  Goal: update bundled pricing constants so usage and quota accounting match the actual OpenRouter-backed bundled offer.

- `ite-cloud-api/src/routes/models.ts`
  Current problem: bundled availability handling is still shaped around the current non-OpenRouter assumptions.
  Goal: make bundled model availability reflect whether the OpenRouter-backed bundled provider path is configured and reachable.

### Web

- `ite-cloud-web/src/pages/BillingPage.tsx`
  Current role: already presents bundled usage and spend windows.
  Goal: keep aligned with the final bundled product language and usage behavior.

- `ite-cloud-web/src/pages/SettingsPage.tsx`
  Current role: explains BYOK setup paths.
  Goal: continue to position BYOK as a parallel option alongside future bundled access.

- `ite-cloud-web/src/pages/DocsPage.tsx`
  Note: the bundled “coming soon” wording should remain until the managed bundled product is actually live.

### Mobile remote

- `ite_remote/lib/remote/models/remote_models.dart`
  Current role: reflects the selected runtime model and runtime state.
  Goal: only follow any user-facing label improvements made by the runtime; no bundled-provider architecture change is needed here.

## Phase 1 Decision

Use OpenRouter as the backend provider for bundled usage.

Preserve BYOK.

Fix runtime classification so bundled routing is driven by the existing bundled and saved-provider differentiators already in the repo, not by the `:cloud` suffix.
