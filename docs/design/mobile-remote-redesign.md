# iTE Remote Mobile App — Professional Redesign Spec

> **Version:** 1.0  
> **Date:** April 2026  
> **Status:** Draft  
> **Reference:** iTE Cloud Web Design System

---

## 1. Concept & Vision

**iTE Remote** is a mobile companion app that connects to your desktop iTE runtime, letting you monitor agent activity, respond to approval requests, and interact with your coding agent from anywhere. The experience should feel like a native messaging app — intimate, real-time, and focused — not a debugging console.

**Core metaphor:** *Your coding agent, in your pocket.*

The design draws from iTE Cloud Web's **"Professional Dark + Editorial Warmth"** philosophy: deep backgrounds with subtle texture, warm off-white text on near-black, IBM Plex Mono for technical elements, Manrope for body copy, and Instrument Serif for moments of display. The mobile adaptation prioritizes thumb-friendly zones, glanceable status, and chat-first interaction.

---

## 2. Design Language

### 2.1 Color Palette

Matches iTE Cloud Web tokens with mobile-specific adjustments:

```dart
// Core Tokens
static const Color bg = Color(0xFF010101);           // Page background
static const Color bgElevated = Color(0xFF0a0a0a);    // Cards, sheets
static const Color bgElevatedStrong = Color(0xFF141414); // Active states
static const Color line = Color(0xFF1a1a1a);          // Dividers
static const Color lineStrong = Color(0xFF2a2a2a);    // Emphasis dividers

// Text
static const Color text = Color(0xFFf4f1ea);          // Primary (warm white)
static const Color textSoft = Color(0xFFc4c1ba);      // Secondary
static const Color textDim = Color(0xFF6a6760);       // Tertiary / labels

// Semantic
static const Color danger = Color(0xFFd9d3cb);        // Errors (warm, not red)
static const Color success = Color(0xFF7ee787);       // Agent actions complete
static const Color accent = Color(0xFF79c0ff);         // Links, active states
static const Color warning = Color(0xFFffa657);       // Pending, caution

// Surface
static const Color surfaceUser = Color(0xFF141414);   // User message bubble
static const Color surfaceAgent = Color(0xFF0a0a0a);  // Agent message bubble
```

### 2.2 Typography

| Style | Font | Size | Weight | Line Height | Letter Spacing |
|-------|------|------|--------|-------------|----------------|
| **Display** | Instrument Serif | 24px | 400 | 1.1 | -0.02em |
| **Title** | Manrope | 18px | 700 | 1.2 | -0.03em |
| **Body** | Manrope | 16px | 400 | 1.5 | 0 |
| **Body Small** | Manrope | 14px | 400 | 1.4 | 0 |
| **Mono** | IBM Plex Mono | 13px | 400 | 1.5 | 0 |
| **Label** | IBM Plex Mono | 11px | 500 | 1.2 | 0.08em |
| **Caption** | IBM Plex Mono | 10px | 400 | 1.3 | 0.06em |

### 2.3 Spacing System (8pt Grid)

```
4px   — micro gap (icon padding)
8px   — tight (inline elements)
12px  — compact (between related items)
16px  — standard (card padding, list gaps)
20px  — comfortable (section spacing)
24px  — relaxed (major section gaps)
32px  — spacious (screen padding top/bottom)
```

### 2.4 Motion Philosophy

| Duration | Curve | Usage |
|----------|-------|-------|
| **Instant** | `easeOut` | Button presses, toggles |
| **Fast** | `cubic-bezier(.16, 1, .3, 1)` 180ms | Cards entering, tabs switching |
| **Normal** | `cubic-bezier(.16, 1, .3, 1)` 280ms | Sheets, modals |
| **Slow** | `easeInOut` 400ms | Page transitions |

**Key animations:**
- Message bubbles: slide up + fade in (200ms)
- Tool call indicators: pulse glow on active
- Approval cards: scale + blur backdrop entrance
- Streaming text: character-by-character with subtle cursor

### 2.5 iOS-Specific Considerations

- Safe area insets for notch/Dynamic Island
- Bottom safe area for home indicator
- Haptic feedback on button presses (`HapticFeedback.lightImpact()`)
- Native-feeling scroll physics (`BouncingScrollPhysics`)
- Pull-to-refresh on thread list

---

## 3. Layout & Structure

### 3.1 Screen Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                      RemoteHomeScreen                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ [●] iTE • main                          ⚙️ [Gear]   │    │  ← Status bar + Settings
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                       │    │
│  │                  TabNavigator                        │    │
│  │                                                       │    │
│  │   ┌───────────┐  ┌───────────┐  ┌───────────┐       │    │
│  │   │   Chat    │  │  Threads   │  │  Runtime   │       │    │
│  │   │   Tab     │  │   Tab      │  │   Tab      │       │    │
│  │   └───────────┘  └───────────┘  └───────────┘       │    │
│  │                                                       │    │
│  │   ┌─────────────────────────────────────────────┐   │    │
│  │   │              Active Tab Content              │   │    │
│  │   │                                               │   │    │
│  │   │  ChatTab / ThreadsTab / RuntimeTab           │   │    │
│  │   │                                               │   │    │
│  │   └─────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Navigation Model

**Bottom Tab Navigation** — 3 tabs, never nested:

| Tab | Icon | Label | Purpose |
|-----|------|-------|---------|
| **Chat** | `message_circle` | Chat | Live conversation with agent |
| **Threads** | `layers` | Threads | Session history, branch switching |
| **Runtime** | `terminal` | Runtime | Connection status, git info |

**Modal Overlays:**
- Approval request → Full-screen modal with backdrop blur
- Thread detail → Push navigation with back gesture
- Settings → Bottom sheet (slide up from gear icon)

### 3.3 Settings Placement

Settings are accessed via a **gear icon** in the top-right corner, presented as a **bottom sheet**. This approach keeps the primary 3-tab navigation clean while providing quick access to configuration.

**Rationale:**
- 3 tabs are cleaner than 4 for thumb-friendly navigation
- Settings are infrequent — don't need permanent nav placement
- Matches iTE Cloud Web's pattern (settings in account dropdown, not nav)
- Bottom sheets can go deep with nested sections without losing context
- Easy to dismiss with swipe-down or backdrop tap

---

## 4. Screen Specifications

### 4.1 Chat Tab — Primary View

**Layout (top to bottom):**

```
┌────────────────────────────────────────────┐
│ [Connection dot] iTE • Branch: main        │  ← Subtle status bar (32px)
├────────────────────────────────────────────┤
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ You: Help me refactor the auth       │  │  ← User bubble (right-aligned)
│  │ module                               │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ iTE: I'll analyze the codebase       │  │  ← Agent bubble (left-aligned)
│  │ first...                             │  │
│  │                                      │  │
│  │ [→ tool_call: git_status]           │  │  ← Inline tool indicator
│  │   ✓ Completed                        │  │
│  │                                      │  │
│  │ Now examining the auth module...     │  │  ← Streaming text
│  │ ▌                                     │  │  ← Cursor (blinking)
│  └──────────────────────────────────────┘  │
│                                            │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │  ← Fade gradient
│                                            │
├────────────────────────────────────────────┤
│ ┌────────────────────────────────────────┐ │
│ │ Tell iTE what to do...                 │ │  ← Composer (auto-expand)
│ └────────────────────────────────────────┘ │
│                                    [Send]  │
└────────────────────────────────────────────┘
```

**Component States:**

| Component | Idle | Active | Streaming | Error |
|-----------|------|--------|-----------|-------|
| **User Bubble** | bg: surfaceUser | — | — | border: danger |
| **Agent Bubble** | bg: surfaceAgent | border-left: accent | + blinking cursor | border: danger |
| **Tool Indicator** | dim text | pulsing glow | — | — |
| **Composer** | collapsed (56px) | expanded (max 180px) | — | border: danger |

**Behavior:**
- Auto-scroll to bottom on new messages (unless user scrolled up)
- Pull up to load older messages (pagination)
- Long-press message to copy
- Tap tool indicator to expand tool details

### 4.2 Approval Modal — Interrupt Overlay

**Trigger:** When agent requests approval (`request_approval` event)

**Layout:**

```
┌────────────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  ← Backdrop blur (8px)
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░┌─────────────────────────────────────┐░░ │
│ ░░│  ⚡ Approval Required              │░░ │  ← Header with icon
│ ░░├─────────────────────────────────────┤░░ │
│ ░░│                                     │░░ │
│ ░░│  Agent wants to run:                │░░ │  ← Context
│ ░░│                                     │░░ │
│ ░░│  ┌───────────────────────────────┐ │░░ │
│ ░░│  │ shell                         │ │░░ │  ← Tool name badge
│ ░░│  │ git commit -m "fix: auth..." │ │░░ │  ← Command preview
│ ░░│  └───────────────────────────────┘ │░░ │
│ ░░│                                     │░░ │
│ ░░│  This will commit changes to 3     │░░ │  ← Impact summary
│ ░░│  files in the auth module.         │░░ │
│ ░░│                                     │░░ │
│ ░░├─────────────────────────────────────┤░░ │
│ ░░│                                     │░░ │
│ ░░│  ┌───────────────┐ ┌──────────────┐ │░░ │
│ ░░│  │    Deny       │ │    Approve   │ │░░ │  ← Action buttons
│ ░░│  └───────────────┘ └──────────────┘ │░░ │
│ ░░│                                     │░░ │
│ ░░└─────────────────────────────────────┘░░ │
└────────────────────────────────────────────┘
```

**Animation:**
- Modal scales from 0.95 → 1.0 with fade (280ms)
- Backdrop blur animates from 0 → 8px (200ms)
- Buttons have haptic feedback on press

### 4.3 Threads Tab — Session History

**Layout:**

```
┌────────────────────────────────────────────┐
│ Threads                              [+]  │  ← Header with new action
├────────────────────────────────────────────┤
│ ┌────────────────────────────────────────┐ │
│ │ 🔴 Active                              │ │  ← Active session badge
│ │                                        │ │
│ │ iTE — Help me build the API            │ │  ← Thread title (first msg)
│ │ Updated 2 min ago • 47 messages       │ │  ← Meta
│ │ Branch: feature/auth                  │ │
│ └────────────────────────────────────────┘ │
│                                            │
│ ┌────────────────────────────────────────┐ │
│ │                                        │ │
│ │ iTE — Refactor the database layer      │ │
│ │ Updated 1 hour ago • 23 messages      │ │
│ └────────────────────────────────────────┘ │
│                                            │
│ ┌────────────────────────────────────────┐ │
│ │                                        │ │
│ │ iTE — Add user authentication          │ │
│ │ Updated yesterday • 89 messages        │ │
│ └────────────────────────────────────────┘ │
│                                            │
│           [End of threads]                 │
└────────────────────────────────────────────┘
```

**Behavior:**
- Tap to open thread detail (push navigation)
- Swipe left to reveal: Delete, Archive actions
- Pull-to-refresh for sync
- FAB or header button to start new thread

### 4.4 Thread Detail Screen — Pushed View

**Layout:**

```
┌────────────────────────────────────────────┐
│ ← Threads                                  │  ← Back nav
├────────────────────────────────────────────┤
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ iTE: I'll help you add              │  │
│  │ authentication to the app.           │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ You: Can you add OAuth with Google?  │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ iTE: Sure! I'll set up OAuth...      │  │
│  └──────────────────────────────────────┘  │
│                                            │
├────────────────────────────────────────────┤
│  [Switch to this thread]                  │  ← Action button
└────────────────────────────────────────────┘
```

**Behavior:**
- Read-only view of message history
- "Switch to this thread" button — sends `switch_session` command
- Back gesture returns to Threads list

### 4.5 Runtime Tab — Status Dashboard

**Layout:**

```
┌────────────────────────────────────────────┐
│ Runtime                                    │
├────────────────────────────────────────────┤
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │  ● Connected                         │  │  ← Connection status
│  │  ws://192.168.1.42:7890              │  │  ← Server address
│  │  Latency: 12ms                      │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ Git                                  │  │
│  ├──────────────────────────────────────┤  │
│  │ Branch      feature/oauth            │  │
│  │ Status      2 changed, 1 untracked    │  │
│  │ Upstream    origin/feature/oauth ↑2   │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ Working Directory                    │  │
│  ├──────────────────────────────────────┤  │
│  │ ~/projects/ite                       │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ Session                              │  │
│  ├──────────────────────────────────────┤  │
│  │ ID       sess_abc123                 │  │
│  │ Started  2 hours ago                  │  │
│  │ Messages 156                         │  │
│  └──────────────────────────────────────┘  │
│                                            │
│         [Disconnect]                      │
│                                            │
└────────────────────────────────────────────┘
```

**Connection States:**

| State | Dot Color | Label | Actions |
|-------|-----------|-------|---------|
| Connected | Green `#7ee787` | Connected | Disconnect |
| Connecting | Yellow `#ffa657` | Connecting... | Cancel |
| Disconnected | Dim | Disconnected | Reconnect |
| Error | Red `#ff7b72` | Connection failed | Retry |

### 4.6 Settings Sheet — Configuration

**Trigger:** Tap gear icon (⚙️) in top-right corner of any screen

**Layout:**

```
┌────────────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  ← Backdrop (dimmed)
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░┌─────────────────────────────────────┐░░ │
│ ░░│ Settings                         [×] │░░ │  ← Drag handle + close
│ ░░├─────────────────────────────────────┤░░ │
│ ░░│                                     │░░ │
│ ░░│ CONNECTION                          │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Server Address                  │ │░░ │
│ ░░│ │ ws://192.168.1.42:7890          │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Auto-reconnect             [ON] │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Pair Code Timeout        [10m]  │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│                                     │░░ │
│ ░░│ DISPLAY                             │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Show Tool Details         [ON]  │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Compact Messages          [OFF] │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│                                     │░░ │
│ ░░│ NOTIFICATIONS                       │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Haptic Feedback          [ON]   │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Sound                   [OFF]  │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│                                     │░░ │
│ ░░│ SESSION                             │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Clear Transcript                │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│ ┌─────────────────────────────────┐ │░░ │
│ ░░│ │ Export Transcript               │ │░░ │
│ ░░│ └─────────────────────────────────┘ │░░ │
│ ░░│                                     │░░ │
│ ░░│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │░░ │
│ ░░│                                     │░░ │
│ ░░│ ABOUT                               │░░ │
│ ░░│ iTE Remote v1.0.0                   │░░ │
│ ░░│                                     │░░ │
│ ░░└─────────────────────────────────────┘░░ │
└────────────────────────────────────────────┘
```

**Settings Categories:**

| Category | Settings | Type |
|----------|---------|------|
| **Connection** | Server Address | Text input (editable) |
| | Auto-reconnect | Toggle |
| | Pair Code Timeout | Picker (5m, 10m, 15m, 30m) |
| | Connection Timeout | Picker (10s, 30s, 60s) |
| **Display** | Show Tool Details | Toggle |
| | Compact Messages | Toggle |
| | Font Size | Segmented (Small, Medium, Large) |
| **Notifications** | Haptic Feedback | Toggle |
| | Sound | Toggle |
| | Approval Alerts | Toggle |
| **Session** | Clear Transcript | Action button (destructive) |
| | Export Transcript | Action button (share sheet) |
| **About** | Version info | Read-only |
| | Check for Updates | Action button |
| | Links (Privacy, Terms) | Text links |

**Behavior:**
- Drag down to dismiss (like iOS settings sheets)
- Tap outside to dismiss
- X button top-right to close
- Scrollable content within sheet
- Sections are collapsible
- Dangerous actions (Clear Transcript) require confirmation dialog

---

## 5. Component Inventory

### 5.1 ConnectionStatusBar

**Appearance:** 32px height, full-width, subtle bottom border

**States:**
- Connected: Green dot + "iTE • [branch name]"
- Disconnected: Dim dot + "Disconnected"
- Reconnecting: Yellow dot + pulsing + "Reconnecting..."

**Position:** Always visible, below safe area, above content

### 5.2 MessageBubble

**Variants:**
- `user` — Right-aligned, darker surface, no avatar
- `agent` — Left-aligned, slightly lighter surface, iTE avatar

**States:**
- Default: Standard appearance
- Streaming: Agent bubble with blinking cursor at end
- Error: Red border, retry icon

**Content:**
- Role indicator (hidden after first message in group)
- Message text (Markdown rendered)
- Tool indicators (inline, collapsible)
- Timestamp (shown on older messages, groupable)

### 5.3 ToolCallIndicator

**Appearance:** Inline badge within agent message

```
┌─────────────────────────────────────┐
│ → shell                            │  ← Tool name
│ git commit -m "fix: auth..."       │  ← Command preview
│ ✓ Completed • 2.3s                  │  ← Status + duration
└─────────────────────────────────────┘
```

**States:**
- Pending: Yellow dot, pulsing
- Running: Yellow dot, animated spinner
- Completed: Green checkmark
- Failed: Red X with error message

### 5.4 Composer

**Appearance:** Rounded rect, subtle border, placeholder text

**States:**
- Collapsed: Single line, 56px height
- Expanded: Multi-line (up to 180px), auto-focus
- Disabled: Dimmed, no interaction (when agent thinking)
- Error: Red border, error message below

**Actions:**
- Send button (enabled when text non-empty)
- Attachment button (for file context) — future
- Voice input button — future

### 5.5 ApprovalCard

**Appearance:** Full-screen modal, rounded corners (16px), backdrop blur

**Sections:**
- Header: Icon + "Approval Required"
- Tool preview: Tool name + command
- Impact summary: What will happen
- Actions: Deny (secondary) + Approve (primary)

**Animation:** Scale + fade entrance (280ms)

### 5.6 ThreadListItem

**Appearance:** Card with rounded corners, hover/press feedback

**Content:**
- Active badge (if current thread)
- Thread title (first user message, truncated)
- Timestamp (relative: "2 min ago", "Yesterday")
- Message count
- Branch name

**States:**
- Default: Standard
- Selected: Accent border-left
- Pressed: Slight scale down (0.98)

### 5.7 StatusCard

**Appearance:** Section container with header + content rows

**Variants:**
- Connection: Status dot + address
- Git: Icon + branch/status/upstream
- Session: Icon + ID/started/messages

**States:** Standard only (read-only display)

### 5.8 SettingsBottomSheet

**Appearance:** Bottom sheet with drag handle, rounded top corners (16px), scrollable content

**Sections:**
- Header with title + close button
- Grouped settings rows (Connection, Display, Notifications, Session, About)
- Section headers in `label` typography style
- Dividers between sections

**States:**
- Expanded: Full height (80% of screen)
- Dragging: Follows finger position
- Collapsed: Dismissed

**Actions:**
- Drag handle for swipe-to-dismiss
- Toggle switches for boolean settings
- Tap rows for picker/modal inputs
- Action buttons for destructive/affirmative actions

---

## 6. Interaction Patterns

### 6.1 Gestures

| Gesture | Location | Action |
|---------|----------|--------|
| Tap | Message | Expand / show details |
| Long press | Message | Copy to clipboard |
| Swipe left | Thread item | Reveal actions |
| Pull down | Any list | Refresh |
| Pull up | Chat | Load older messages |
| Swipe right | Thread detail | Return to list |

### 6.2 Haptics

| Event | Feedback |
|-------|----------|
| Button press | `HapticFeedback.lightImpact()` |
| Approval granted | `HapticFeedback.mediumImpact()` |
| Approval denied | `HapticFeedback.heavyImpact()` |
| Message sent | `HapticFeedback.selectionClick()` |
| Error | `HapticFeedback.vibrate()` |

### 6.3 Error States

| Error | UI Response |
|-------|--------------|
| Connection lost | Banner + auto-reconnect attempt |
| Message failed | Red border + retry button |
| Approval timeout | Auto-dismiss after 60s + notification |
| Token expired | Modal prompting re-authentication |

---

## 7. State Management

### 7.1 App State (Riverpod)

```dart
// Connection
@riverpod
class ConnectionState extends _$ConnectionState {
  // connected, connecting, disconnected, error
}

// Runtime
@riverpod
class RuntimeState extends _$RuntimeState {
  // branch, status, upstream, workingDir, session
}

// Chat
@riverpod
class ChatMessages extends _$ChatMessages {
  // List<Message>, streaming state
}

// Threads
@riverpod
class ThreadList extends _$ThreadList {
  // List<ThreadSummary>
}

// Pending Approval
@riverpod
class PendingApproval extends _$PendingApproval {
  // ToolCall?, timeout countdown
}

// Settings
@riverpod
class AppSettings extends _$AppSettings {
  // serverAddress, autoReconnect, pairTimeout, showToolDetails, etc.
}
```

### 7.2 WebSocket Event Mapping

| Event Type | State Update | UI Reaction |
|------------|--------------|-------------|
| `remote_state` | Initialize all state from payload | Populate screens |
| `agent_event` | Append to chat messages | Scroll to bottom |
| `approval_request` | Set `pendingApproval` | Show modal |
| `approval_response` | Clear `pendingApproval` | Dismiss modal |
| `cancel_turn` | Clear streaming state | Stop cursor animation |
| `switch_session` | Update `currentThread` | Navigate to thread |

---

## 8. Technical Considerations

### 8.1 Architecture

```
lib/
├── main.dart
├── app.dart
├── core/
│   ├── theme/
│   │   ├── app_colors.dart      ← Design tokens
│   │   ├── app_typography.dart  ← Font styles
│   │   └── app_theme.dart       ← ThemeData
│   └── utils/
│       └── haptics.dart
├── data/
│   ├── models/
│   │   ├── message.dart
│   │   ├── thread.dart
│   │   ├── approval_request.dart
│   │   └── runtime_info.dart
│   └── repositories/
│       └── remote_repository.dart
├── presentation/
│   ├── providers/
│   │   ├── connection_provider.dart
│   │   ├── chat_provider.dart
│   │   ├── threads_provider.dart
│   │   └── runtime_provider.dart
│   ├── screens/
│   │   ├── home_screen.dart
│   │   ├── chat_tab.dart
│   │   ├── threads_tab.dart
│   │   ├── thread_detail_screen.dart
│   │   └── runtime_tab.dart
│   └── widgets/
│       ├── connection_status_bar.dart
│       ├── message_bubble.dart
│       ├── tool_call_indicator.dart
│       ├── composer.dart
│       ├── approval_modal.dart
│       ├── thread_list_item.dart
│       ├── status_card.dart
│       └── settings_bottom_sheet.dart
└── shared/
    └── app_colors.dart          ← Re-export for convenience
```

### 8.2 Dependencies

```yaml
dependencies:
  flutter:
    sdk: flutter
  flutter_riverpod: ^2.4.9
  riverpod_annotation: ^2.3.3
  go_router: ^13.0.0
  flutter_markdown: ^0.6.18
  gap: ^3.0.1
  google_fonts: ^6.1.0
  flutter_animate: ^4.3.0
```

### 8.3 Asset Requirements

| Asset | Type | Purpose |
|-------|------|---------|
| `assets/icons/agent.svg` | Vector | iTE avatar in chat |
| `assets/icons/terminal.svg` | Vector | Runtime tab icon |
| `assets/icons/layers.svg` | Vector | Threads tab icon |
| `assets/icons/message.svg` | Vector | Chat tab icon |

---

## 9. Implementation Priority

### Phase 1: Core Experience
1. App shell with bottom navigation
2. Connection status bar
3. Basic chat UI (messages + composer)
4. WebSocket connection logic
5. Event handling (remote_state, agent_event)

### Phase 2: Full Feature Set
6. Approval modal
7. Thread list + detail views
8. Runtime status dashboard
9. Error states + reconnection logic
10. Haptic feedback

### Phase 3: Settings + Polish
11. Settings bottom sheet
12. Animations (message entrance, streaming cursor)
13. Markdown rendering improvements
14. Pull-to-refresh
15. Swipe actions on threads
16. Accessibility improvements

---

## 10. Design Verification Checklist

Before shipping, verify:

- [ ] All text meets contrast ratio (4.5:1 minimum)
- [ ] Touch targets are minimum 44x44px
- [ ] Safe areas respected on all iPhone models
- [ ] Dark mode only (matches iTE brand)
- [ ] Animations respect `MediaQuery.of(context).disableAnimations`
- [ ] Keyboard handling (composer doesn't get hidden)
- [ ] Memory efficient (lazy load older messages)
- [ ] Offline graceful degradation (show cached threads)

---

## Appendix A: Reference Assets

### iTE Cloud Web Auth Page (Reference)
![Auth Page Reference](https://ite.kiishi.space/ite-prev.png)

### iTE Agent Logo (Transparent)
Transparent background version suitable for chat avatars and branding.

**Source:** `ite-cloud-web/dist/assets/ite-image-DU2WVwTP.png`  
**Local copy:** `ite_remote/assets/images/ite-logo-transparent.png`

```
Dimensions: 886 × 548px
Format: PNG with RGBA (transparent background)
```

**Usage in app:**
- `assets/images/ite-logo-transparent.png` → Agent avatar in message bubbles
- Can be placed on any background color due to transparency

### iTE Cloud Web Preview (Landing Page)
Non-transparent version with background, suitable for marketing materials and onboarding screens.

**Source:** `landing-site/ite-preview.png`  
**Local copy:** `ite_remote/assets/images/ite-preview.png`

```
Dimensions: 1408 × 768px
Format: PNG with RGB (solid background)
```

### Agent Visualization (Reference)
The streaming agent visualization in iTE Cloud Web provides inspiration for the chat streaming UX.

---

## Appendix B: Color Comparison

| Purpose | iTE Cloud Web | Mobile App |
|---------|---------------|------------|
| Background | `#010101` | `#010101` |
| Elevated | `#0a0a0a` | `#0a0a0a` |
| Text Primary | `#f4f1ea` | `#f4f1ea` |
| Text Secondary | rgba(244,241,234,.74) | `#c4c1ba` |
| Text Tertiary | rgba(244,241,234,.44) | `#6a6760` |
| Accent | — | `#79c0ff` |
| Success | — | `#7ee787` |
| Warning | — | `#ffa657` |
| Danger | `#d9d3cb` | `#d9d3cb` |

---

*Document maintained by: iTE Design Team*  
*Last updated: April 2026*
