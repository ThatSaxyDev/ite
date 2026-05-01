# iTE Admin Flutter App Plan

## Goal

Build a private iTE Admin app in Flutter for personal sideloading on mobile and macOS.

The app should manage iTE Cloud operational workflows without using the public web account UI as the control surface. It should borrow visual language and Flutter architecture from `ite_remote`, while talking directly to `ite-cloud-api` over HTTPS.

Target platforms:

- iOS / Android phone layout
- macOS desktop layout

## Admin Auth Direction

Use fixed admin credentials configured in the `ite-cloud-api` environment.

Required backend environment:

```env
ADMIN_APP_EMAIL=you@example.com
ADMIN_APP_PASSWORD_HASH=<argon2-or-bcrypt-hash>
ADMIN_APP_SESSION_SECRET=<long-random-secret>
```

Generate the password hash from `ite-cloud-api`:

```bash
npm run admin:hash -- "your-private-admin-password"
```

Then put the printed Argon2 hash into `ADMIN_APP_PASSWORD_HASH`.

Production does not compare against a plaintext password. The auth shape is:

1. The admin app posts `email` and `password` to `POST /admin/auth/login`.
2. The backend checks `email === ADMIN_APP_EMAIL`.
3. The backend verifies the password against `ADMIN_APP_PASSWORD_HASH`.
4. The backend issues a signed admin session token.
5. The Flutter app stores that token in secure storage.
6. Admin routes require `Authorization: Bearer <admin-session-token>`.

This still gives the fixed-secret workflow you want, but avoids leaking a reusable plaintext password from process/env dumps, logs, crash output, or provider dashboards.

## Why Not Reuse Browser Auth

The current admin routes use `ADMIN_EMAILS` and Better Auth browser sessions. That works for the web app, but it is awkward for a sideloaded Flutter admin app because:

- mobile/macOS native auth would need cookie persistence and web auth callback handling
- GitHub OAuth adds deep-link complexity
- admin access becomes coupled to a normal user session
- personal operational controls should be isolated from regular account UX

The admin app should have a separate admin auth path.

## Backend Work

Add a dedicated admin auth and admin API surface in `ite-cloud-api`.

Proposed files:

- `ite-cloud-api/src/routes/admin-auth.ts`
- `ite-cloud-api/src/routes/admin.ts`
- `ite-cloud-api/src/lib/admin-auth.ts`
- updates to `ite-cloud-api/src/lib/config.ts`
- updates to `ite-cloud-api/src/app.ts`
- updates to `ite-cloud-api/src/lib/contracts.ts`

Proposed routes:

```text
POST /admin/auth/login
POST /admin/auth/logout
GET  /admin/auth/me

GET  /admin/overview
GET  /admin/users?query=<email-or-id>
GET  /admin/users/:userId
POST /admin/users/:userId/bundled-access

GET  /admin/usage/resets
POST /admin/usage/reset
POST /admin/usage/simulate
```

Existing `/admin/usage/*` routes can be migrated from Better Auth admin checks to the new admin bearer session, or support both during transition.

## Admin App Architecture

Create `ite_admin` as its own Flutter app with patterns copied from `ite_remote`.

Recommended structure:

```text
ite_admin/lib/
├── main.dart
├── core/
│   ├── config/
│   │   ├── dependencies.dart
│   │   └── app_config.dart
│   ├── network/
│   │   └── api_client.dart
│   ├── storage/
│   │   └── secure_store.dart
│   └── theme/
│       ├── app_colors.dart
│       ├── app_theme.dart
│       └── app_typography.dart
├── admin/
│   ├── models/
│   ├── repositories/
│   ├── notifiers/
│   ├── screens/
│   └── widgets/
└── shared/
    ├── widgets/
    └── utils/
```

State and dependencies:

- `flutter_riverpod` for app state
- `get_it` for shared services if useful
- `dio` for HTTP
- `flutter_secure_storage` for admin session token
- `shared_preferences` for API base URL and display preferences
- `phosphor_flutter` for icons
- `google_fonts` for matching `ite_remote` typography
- `intl` for dates, currency, and usage formatting

## UX Scope

MVP screens:

1. Login
   - API URL field
   - admin email
   - admin password
   - session persistence

2. Overview
   - total users
   - bundled-enabled users
   - recent usage spend
   - recent admin actions
   - backend health/config summary

3. Users
   - search by email or user ID
   - user detail page
   - entitlement status
   - usage windows
   - recent activity

4. Entitlements
   - enable/disable bundled access for a target user
   - show plan key and last updated time

5. Usage Tools
   - simulate usage by profile
   - reset usage for one user
   - reset usage globally
   - show reset history

6. Settings
   - API base URL
   - signed-in admin email
   - logout

## Mobile And macOS Layout

The same Flutter codebase should adapt layout based on width.

Mobile:

- bottom navigation or compact rail
- stacked metric cards
- full-screen detail pages
- destructive actions require confirmation sheets
- large touch targets

macOS:

- persistent left rail
- master-detail user search and user detail
- wider metric grid
- inline admin tools where safe
- keyboard-friendly text fields

Responsive breakpoints:

```text
compact: < 700px
desktop: >= 900px
```

Between those, use tablet-style two-column layouts where they fit.

## Visual Direction

Use `ite_remote` as the base:

- black background
- warm off-white text
- square corners
- mono uppercase labels
- restrained semantic colors only for success/warning/error
- dense operational cards rather than marketing-style panels

The admin app should feel more like an operations console than the remote app:

- more tables and metrics
- less chat emphasis
- clear dangerous-action affordances
- confirmation before global resets

## Security Notes

This is private tooling, but the controls are powerful. Minimum safeguards:

- do not log submitted admin passwords
- prefer password hash env over plaintext password env
- use short-lived signed admin sessions
- store tokens only in secure storage
- require confirmation for global resets
- record admin audit events for usage simulations, resets, and entitlement changes
- rate-limit admin login attempts

Nice-to-have later:

- device label on login
- session revocation
- optional TOTP or one-time recovery code
- allowlist app versions

## Implementation Phases

### Phase 1: Backend Admin Auth

- add env config for fixed admin credentials
- add login/me/logout routes
- add bearer-session admin guard
- update existing admin usage routes to accept the new guard
- add tests for successful login, failed login, forbidden access, and protected route access

### Phase 2: Backend Admin Data Routes

- add user search
- add user detail
- add target-user bundled access toggle
- add overview summary
- log admin audit activity

### Phase 3: Flutter Foundation

- replace default counter app
- add dependencies
- port theme and core app shell from `ite_remote`
- add responsive shell for mobile and macOS
- add secure token storage and API client

### Phase 4: Flutter MVP Screens

- login
- overview
- user search/detail
- entitlement toggle
- usage simulate/reset
- settings/logout

### Phase 5: Verification

Run:

```bash
cd ite-cloud-api && npm run typecheck
cd ite_admin && flutter analyze
cd ite_admin && flutter test
```

Also manually verify:

- mobile narrow layout
- macOS wide layout
- logout clears token
- expired/invalid token returns to login
- global reset requires explicit confirmation

## Open Decision

The main implementation decision is password verification:

- Preferred: `ADMIN_APP_PASSWORD_HASH` with bcrypt or argon2.
- Simpler: `ADMIN_APP_PASSWORD` plaintext env comparison.

I recommend hash-first. It still behaves like a fixed secret known only to you, but it is safer if environment values are ever exposed.
