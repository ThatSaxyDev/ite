# Draft: Remote Mobile App Documentation Plan

## Overview

This document outlines how to add documentation for the iTE Remote Mobile App feature. The feature connects the Flutter `ite_remote` app to the iTE Reup runtime via a local TCP bridge.

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        iTE Runtime (Python)                     │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │  Reup UI     │───▶│ RemoteRuntimeServer │───▶│ TCP Server   │  │
│  │  (Textual)   │    │  (src/ite/remote/) │    │ (0.0.0.0:0)  │  │
│  └──────────────┘    └──────────────────┘    └───────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Line-delimited JSON over TCP
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ite_remote (Flutter App)                     │
│  ┌──────────────────────┐    ┌─────────────────────────────┐    │
│  │ RemoteRuntimeRepository│───▶│ RemoteRuntimeNotifier      │    │
│  │ (socket I/O, auth)    │    │ (UI state management)       │    │
│  └──────────────────────┘    └─────────────────────────────┘    │
│  ┌──────────────────────┐    ┌─────────────────────────────┐    │
│  │ SettingsSheet         │    │ Chat/Session Views          │    │
│  │ (connection UI)       │    │ (live monitoring)           │    │
│  └──────────────────────┘    └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Where Documentation Lives

### 1. `docs-new/` — Markdown Source Files
Location: `/docs-new/`

These are markdown files used by `ite-cloud-web`. The DocsPage.tsx renders them as a single-page documentation site.

**Files to create/add:**
- `docs-new/remote.md` — New file for remote mobile app feature

### 2. `ite-cloud-web/src/pages/DocsPage.tsx` — Navigation Entry
Location: `ite-cloud-web/src/pages/DocsPage.tsx`

The `DOC_NAV` array defines sidebar navigation items. Need to add an entry for "Remote" or "Mobile App".

**Current entries:**
```tsx
const DOC_NAV: readonly DocNavItem[] = [
  { id: "intro", label: "Intro", description: "..." },
  { id: "prerequisites", label: "Prerequisites", description: "..." },
  // ... existing entries
  { id: "mcp", label: "MCP", description: "External tool servers." },
] as const;
```

**Need to add:**
```tsx
{ id: "remote", label: "Remote", description: "Connect from your phone." },
```

### 3. `docs/ite-remote-runtime-connection.md` — Technical Reference
Location: `docs/ite-remote-runtime-connection.md`

Already exists. Contains the deep-dive technical explanation of the protocol. This should remain as-is or be enhanced.

---

## Proposed Doc Structure

### `docs-new/remote.md` Content Outline

```markdown
# Remote: Code from Your Phone

Control iTE from your mobile device with the **iTE Remote** app.

## Overview

iTE Remote is a Flutter app that connects to your iTE runtime over your local network. The phone acts as a remote monitor and control surface for your laptop's session.

## Requirements

- iTE runtime running (`ite` command)
- iTE Remote app installed on your phone
- Both devices on the same WiFi network

## Getting Started

### 1. Start the Remote Bridge

In iTE, run:

    /remote on

You'll see connection details:

```
Host: 192.168.x.x:9123
Pair code: 123456
Connect URL: ite://c/192.168.x.x/9123/123456
```

### 2. Connect from the App

1. Open the iTE Remote app
2. Tap Connect
3. Grant camera access (for QR code) or paste the connect URL
4. Enter the pair code if prompted

## How It Works

iTE Remote uses a direct TCP connection between your phone and laptop:

- **No cloud relay** — Connection is entirely local
- **No internet required** — Works over LAN
- **Pair code authentication** — 6-digit code expires after 10 minutes
- **Reconnect token** — After first pairing, the app remembers the session

### Protocol

The runtime exposes a narrow remote-control API:

| Frame Type | Direction | Purpose |
|------------|-----------|---------|
| `hello` | App → Runtime | Initial handshake |
| `paired` | Runtime → App | Authentication success |
| `remote_state` | Runtime → App | Session snapshot |
| `agent_event` | Runtime → App | Live streaming updates |
| `submit_prompt` | App → Runtime | Send message |
| `cancel_turn` | App → Runtime | Stop current operation |
| `approval_response` | App → Runtime | Approve/deny tool calls |

## Troubleshooting

### Can't connect

1. Verify both devices are on the same network
2. Check firewall allows inbound on the runtime port
3. Regenerate the pair code with `/remote off` then `/remote on`

### Connection drops

The reconnect token survives app restarts but not runtime restarts. Re-pair if the runtime was restarted.

## Security

- Pair codes expire after 10 minutes
- Tokens are stored only in memory on the runtime
- No TLS on local connections (LAN-only)
- Never share pair codes with untrusted parties

## See Also

- [Remote Runtime Connection](/docs/ite-remote-runtime-connection.md) — Technical deep-dive
- [ite_remote repository](https://github.com/...) — Flutter app source
```

---

## Implementation Steps

### Step 1: Add Navigation Entry

**File:** `ite-cloud-web/src/pages/DocsPage.tsx`

Add to `DOC_NAV` array, after `mcp`:

```tsx
{
  id: "remote",
  label: "Remote",
  description: "Connect from your phone.",
},
```

### Step 2: Create Documentation File

**File:** `docs-new/remote.md`

Create with content from outline above.

### Step 3: Verify in DocsPage.tsx

Add corresponding `<section>` with `id="remote"` in the article body, OR rely on linking to the markdown file directly (check existing pattern for how MCP/other sections are rendered).

### Step 4: Link Technical Reference

Consider adding a reference link from `docs-new/remote.md` to `docs/ite-remote-runtime-connection.md` for users who want the deep-dive.

---

## File Inventory

| File | Action | Notes |
|------|--------|-------|
| `docs-new/remote.md` | **CREATE** | Main remote app docs |
| `docs/ite-remote-runtime-connection.md` | **EXISTING** | Protocol deep-dive (reference from new doc) |
| `ite-cloud-web/src/pages/DocsPage.tsx` | **MODIFY** | Add nav entry + section |

## Alternative: Keep All Content in DocsPage.tsx

If the markdown file approach adds complexity, the entire remote section could be added inline in `DocsPage.tsx` as a new `<section id="remote">` block, similar to existing sections like `intro`, `prerequisites`, `install`, etc.

**Pros:** Single source of truth, no additional files
**Cons:** Larger file, harder to version-control diffs

---

## Questions / Decisions Needed

1. **Where to host the technical reference?** Keep in `docs/` or move to `docs-new/`?
2. **Screenshot/visual assets?** Should we include UI screenshots from the Flutter app?
3. **QR code flow documentation?** Is camera/QR scanning implemented?
4. **Link to Flutter app store listing?** When available, add download links
