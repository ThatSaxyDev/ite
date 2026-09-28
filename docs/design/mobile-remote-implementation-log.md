# iTE Remote Flutter — Implementation Log

**Date:** 2026-04-22  
**Project:** iTE Remote Mobile Redesign  
**Status:** In Progress

---

## Overview

This document tracks the implementation of the iTE Remote Flutter app redesign, translating the iTE Cloud Web design language into a mobile-first experience.

---

## Design System

### Color Palette (Monochromatic B&W)

| Token | Hex | Usage |
|-------|-----|-------|
| `bg` | `#000000` | Page background - pure black |
| `bgElevated` | `#0a0a0a` | Cards, sheets, elevated surfaces |
| `bgElevatedStrong` | `#141414` | Active states, selected items |
| `line` | `#1a1a1a` | Subtle dividers |
| `lineStrong` | `#2a2a2a` | Emphasis dividers, borders |
| `text` | `#f4f1ea` | Primary text - warm white |
| `textSoft` | `#c4c1ba` | Secondary text |
| `textDim` | `#6a6760` | Tertiary text, labels |

**Semantic Colors** (minimal use):

| Token | Hex | Usage |
|-------|-----|-------|
| `success` | `#7ee787` | Connected, success states |
| `warning` | `#ffa657` | Pending, caution |
| `errorColor` | `#f4d3c9` | Errors |

**Tool Category Colors** (monochromatic differentiation):

| Category | Hex | Tools |
|----------|-----|-------|
| Read | `#e8e8e8` | read_file, read_pdf, etc. |
| Write | `#c8c8c8` | write_file, edit, etc. |
| Explore | `#a8a8a8` | grep, glob, list_dir |
| Execute | `#888888` | shell commands |
| Web | `#b0a898` | web_search, http_request |
| Git | `#98a8b0` | git_status, git_diff, etc. |

### Typography

| Style | Font | Size | Weight |
|-------|------|------|--------|
| Display | Instrument Serif | 24px | 400 |
| Title | Manrope | 18px | 700 |
| Body | Manrope | 15px | 400 |
| Mono | IBM Plex Mono | 11-13px | 400-500 |
| Label | IBM Plex Mono | 10px | 500 |

### Design Principles

- **Straight edges only** — No border-radius, sharp corners throughout
- **Monochromatic palette** — Black/white only, with strategic color for tool categories
- **Breathing room** — Generous padding for readability
- **No decorative color** — Color only when semantically necessary

---

## Screen Architecture

### Home Screen

- Bottom tab navigation: Chat | Threads | Runtime
- Connection status bar at top (shows workspace + connection state)
- Settings gear icon opens settings sheet

### Chat Tab

- Message bubbles with markdown rendering
- Composer bar with send button
- "Agent is thinking..." indicator when turn is running
- Stop button for cancellation

**Collapsible Messages:**
- Long messages (>6 lines or >400 chars) are collapsible
- Always start collapsed
- Tap header to expand/collapse
- Full markdown rendering when expanded

### Threads Tab

- List of open sessions
- Active session highlighted with accent border
- "RUNNING" / "ACTIVE" badges
- Shows turn count and workspace

### Runtime Tab

- Connection status card
- Runtime info (model, workspace, plan mode, turn status)
- Session info (ID, message count, open sessions)
- Live activity feed
- Refresh / Stop Turn buttons

### Settings Sheet

- Connection config (host, port, pair code)
- Connect/Disconnect button
- Display preferences
- Notification settings

---

## Tool Card System

### Humanized Tool Names

Tool names are converted from `snake_case` to readable labels:

| Tool | Title | Completed Title |
|------|-------|-----------------|
| `read_file` | Reading file | Completed reading |
| `write_file` | Writing file | Saved file |
| `edit` | Editing file | Updated file |
| `grep` | Searching code | Finished searching |
| `shell` | Running command | Command finished |
| `web_search` | Searching web | Search complete |

### Collapsible Tool Cards

- Tool cards always start collapsed
- Show tool title + category color + duration (if completed)
- Expand icon only visible when command content exists
- Tap to expand and see command details
- No separate expand button; toggle in title row only

---

## Components

### MessageBubble

- User messages: right-aligned, solid background
- Agent messages: left-aligned, lighter background
- Agent header: "iTE" label with expand toggle for long content
- Markdown rendering with custom stylesheet
- Code blocks with monospace font

### ToolCallIndicator

- Status icon (square for pending/completed, circle for running)
- Humanized title text
- Category-based coloring
- Collapsible command content
- Duration display for completed tools

### ConnectionStatusBar

- Status dot (green/amber/gray)
- Workspace name
- Connection state text
- Settings gear icon

### ApprovalModal

- Full-screen dialog for approval requests
- Shows tool name, command, description
- Approve/Deny buttons
- Non-dismissible (must choose)

---

## Known Issues & Fixes

### Send button not working

**Problem:** Text was cleared from controller but never sent to notifier.

**Fix:** Modified `submitPrompt` to accept optional message parameter and pass text directly from controller:

```dart
void _submitPrompt() {
  final text = _composerController.text.trim();
  if (text.isEmpty) return;
  ref.read(remoteRuntimeNotifierProvider.notifier).submitPrompt(text);
  _composerController.clear();
}
```

### Settings sheet not closing on tap outside

**Problem:** Modal bottom sheet needed explicit dismiss handling.

**Fix:** Wrapped content in GestureDetector that calls `Navigator.pop()` and prevented propagation on inner content.

### Tool card expand issues

**Problem:** 
1. Expand icon in title row wasn't affecting card size
2. Separate expand button at top of content
3. Cards started expanded

**Fix:**
1. Removed inner expand button, only toggle in header
2. Replaced AnimatedCrossFade with conditional rendering
3. Always initialize `_isExpanded = false` in `didChangeDependencies`

### Message bubble expand issues

**Problem:** Messages started expanded and expanded on scroll.

**Fix:** 
1. Added `didUpdateWidget` to reset expansion when content changes
2. Changed initialization to always start collapsed
3. Removed separate header expand button

---

## Dependencies Added

```yaml
flutter_markdown: ^0.7.7
```

---

## Files Created/Modified

### Created

| File | Purpose |
|------|---------|
| `lib/core/utils/tool_utils.dart` | Tool name humanization + categories |
| `lib/core/theme/app_theme.dart` | Theme configuration |
| `lib/core/theme/app_typography.dart` | Typography constants |
| `lib/remote/screens/home_screen.dart` | Main scaffold |
| `lib/remote/screens/connection_status_bar.dart` | Status bar |
| `lib/remote/screens/chat_tab.dart` | Chat interface |
| `lib/remote/screens/threads_tab.dart` | Sessions list |
| `lib/remote/screens/runtime_tab.dart` | Runtime dashboard |
| `lib/remote/screens/settings_sheet.dart` | Settings modal |
| `lib/remote/widgets/message_bubble.dart` | Markdown message bubbles |
| `lib/remote/widgets/tool_call_indicator.dart` | Collapsible tool cards |
| `lib/remote/widgets/approval_modal.dart` | Approval dialog |

### Modified

| File | Change |
|------|--------|
| `lib/shared/app_colors.dart` | Monochromatic palette + tool colors |
| `lib/main.dart` | Simplified to dark-only theme |
| `pubspec.yaml` | Added flutter_markdown |
| `test/design_tokens_test.dart` | Updated color assertions |

---

## Verification

```bash
cd ite_remote
flutter analyze    # No errors
flutter test       # 6/6 passed
flutter build macos --debug  # Success
```

---

## Next Steps

- [ ] Connect to actual iTE runtime and test streaming
- [ ] Implement real-time activity feed updates
- [ ] Add pull-to-refresh on threads tab
- [ ] Implement session switching with proper state
- [ ] Test approval modal flow
- [ ] Mobile-specific optimizations (safe areas, gestures)
- [ ] Test on physical iOS device
