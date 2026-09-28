# iTE Textual Design Guide

This document is the design contract for `iTE` in Textual.

It is not a generic brand deck and it is not a web UI style guide. It exists to capture what actually works in a terminal application, what fails in Textual, and how we should design the shell going forward without repeating layout regressions.

`src/ite/ui/reup/` is the implementation path. The product name is `iTE`.

---

## 1. North Star

`iTE` should feel like a premium terminal instrument:

- quiet
- compact
- editorial
- legible under load
- asymmetrical in a deliberate way

The interface should not feel like:

- a web dashboard squeezed into a terminal
- a pile of heavy bordered cards
- a toy CLI with random accent colors
- a side-project TUI full of decorative lines

The correct mental model is:

- open canvas first
- contained surfaces only when they help comprehension
- spacing as structure
- color as state
- very little chrome
- one active Textual theme driving the full app

---

## 2. Textual Reality

Design for what Textual and terminals are actually good at.

### Terminal Constraints

- We have one practical type family: monospace.
- Hierarchy comes from weight, spacing, casing, and surface contrast.
- Every extra row matters.
- Borders are expensive visually.
- Over-nesting containers makes spacing harder to reason about.
- “Auto” sizing is useful, but only when the widget model is stable.

### Textual Constraints

- CSS-like layout is powerful, but not web CSS. Do not assume browser behavior.
- `width: auto` and `max-width` can behave unexpectedly when nested inside generic containers.
- Scroll padding and internal content spacing are not interchangeable.
- If a layout is critical, make it explicit in widget structure instead of hoping CSS will infer intent.
- Widget choice matters. A dedicated `Static` often behaves more reliably than forcing everything through one generic card component.

### Core Rule

If a visual behavior is important, encode it in the widget structure first and style it second.

Examples:

- User messages should use a dedicated user-message path.
- Tool activity can use shared card styling because it is structurally similar.
- Empty-state centering should be done with a centered renderable, not just outer container guesses.

---

## 3. Visual System

### Theme Source Of Truth

`iTE` now uses the active Textual theme as the single source of truth for UI color.

- The app may choose an initial theme at startup.
- After startup, the active Textual theme owns color.
- Theme switching must affect the full runtime, not only the shell.
- Palette themes such as `flexoki`, `gruvbox`, `catppuccin-*`, `solarized-*`, etc. must visibly change the app.

Do not treat `textual-light` and `textual-dark` as the only real themes.

They are default starting points, not the entire design system.

### Token Rule

Prefer valid Textual theme tokens first.

Use tokens such as:

- `$background`
- `$surface`
- `$surface-darken-1`
- `$panel`
- `$panel-lighten-1`
- `$border`
- `$foreground`
- `$foreground-muted`
- `$foreground-disabled`
- `$primary`
- `$primary-muted`
- `$success`
- `$success-muted`
- `$warning`
- `$warning-muted`
- `$text-primary`
- `$text-secondary`
- `$text-success`
- `$text-warning`
- `$text-error`

Do not invent token names and hope Textual supports them.

Do not rely on a `Screen:light` rescue layer as the main theme strategy.

### Contrast Rule

Theme fidelity is important, but readability is not optional.

- If a light theme produces unreadable foreground or accent colors in dense Rich renderables, introduce a contrast floor.
- That floor should be derived from theme lightness, not guessed from the terminal brand.
- Dark themes should keep their richer original rendering if they are already readable.
- Light themes may need darker semantic accents than the raw generated theme tokens provide.

The practical rule is:

- detect whether the active theme background is light
- if it is, darken low-contrast foreground, secondary, muted, and semantic accent styles enough to remain readable
- do not globally flatten all themes just to save one terminal / theme combination

If the app looks good in one terminal and bad in another, verify the actual rendered contrast first before adding terminal-specific behavior.

### Base Palette

- Canvas: `#131315`
- Surface low: `#181a1d`
- Surface mid: `#202226`
- Surface high: `#232327`
- Deep recess / code well: `#0e0e10`

### Text

- Primary: `#edf1f7`
- Secondary: `#d7deea`
- Muted: `#8c93a1`

### Accent Use

- Success / active intent: muted emerald, not neon
- Informational / selected state: cool slate-blue
- Warning / destructive intent: restrained amber

Accent color is not decoration. It should signal:

- action
- state
- status
- selected focus

### No-Line Rule

Do not solve hierarchy with borders by default.

Use, in order:

1. background shift
2. spacing
3. alignment
4. typography
5. border only when a true frame is needed

Borders are still appropriate for:

- composer shell
- modals
- command palette
- code fences when readability benefits

They are usually wrong for:

- tool cards
- assistant content
- feed separators
- session rows

---

## 4. Hierarchy in a Monospace UI

Because the terminal gives us one family, hierarchy must come from restraint.

### Use

- bold for titles and labels that actually matter
- muted text for metadata
- right-aligned metadata rails
- stronger spacing between major regions than between minor elements
- lowercase or sentence case for conversational copy

### Avoid

- all caps everywhere
- too many badges
- too many simultaneous accent colors
- stacked labels above every piece of content

### Copy Rules

- `iTE` voice should be concise and direct.
- Do not invent branding language in the interface.
- Keep helper text minimal.
- High-signal emoji are allowed when they improve scanability.
- Avoid childish or loud icon choices when a quieter symbol works better.

---

## 5. Layout Rules

### Top Bar

The top bar is identity and status, not a toolbar.

- Keep it slim.
- `iTE` remains the center identity mark.
- Thread title is primary.
- Workspace and route metadata belong on the right.
- Avoid large buttons in the header.

### Session Strip

The session strip should only consume space when it is actually needed.

- If there is one session, hide the strip entirely.
- Any top spacing above the first row of content should belong to scrollable content when possible, not to dead chrome.
- Session tabs should read like compact tokens, not a secondary navigation app.

### Thread Navigation

Thread switching now belongs in a left-side navigation panel, not in a large top strip.

The thread nav follows these rules:

- The hamburger affordance lives at the far left of the top bar.
- The hamburger should be available even when there is only one thread.
- The panel opens from the left, matching the direction implied by the control.
- The panel is slimmer than the command/help panel and remains collapsible with a close control.
- The top of the panel contains a solid `New chat` action that behaves like `/new`.
- Thread rows are text-like navigation items, not solid buttons.
- Thread rows align left and stay on one line.
- Long thread titles must truncate with `...`.
- The current thread is shown with a subtle selected-row treatment and a thin left-edge indicator, not with inline `current` text.
- Empty draft threads named `New thread` should not appear as a row until they have real content.
- Newly created real threads should appear at the top of the nav once they become visible.
- Saved former sessions from `/sessions` should appear in the nav, but `/sessions` itself remains available for users who prefer commands.
- Row order must remain stable while switching. Selecting a thread must not cause rows to jump around.

Do not put a large `/threads` text button on the right side of the header for this feature. It breaks header alignment and contradicts the left-opening panel.

### Conversation Area

The feed is the core canvas.

- Keep it visually open.
- Feed spacing should be intentional but tight.
- The feed should claim as much vertical space as possible.
- Empty dead bands above or below the feed are almost always a bug.

### Composer

The composer is a docked control surface.

- It can have a frame.
- It should touch the feed above cleanly.
- It must preserve the bottom action rail.
- It should look stable, not float awkwardly with random gaps.

---

## 6. Feed Design Rules

The feed is not a list of interchangeable cards.

There are different content classes and they need different treatments.

### Assistant Content

Assistant output should feel integrated into the canvas.

- Prefer open text blocks.
- Avoid wrapping ordinary assistant prose in heavy cards.
- Use recessed framing only for code, tools, plans, errors, and special content.

### User Messages

User messages are the one intentionally boxed conversational element.

- They live on the right.
- They should size to content first, then clamp at a max width.
- They should not stretch into long horizontal bars when the message is short.
- They should not disappear because of fragile layout wrappers.
- They need a little vertical padding so they do not feel pasted onto the feed.

The implemented rule is:

- dedicated user-message widget path
- dedicated user-message row
- explicit content-derived width
- max-width clamp
- right alignment at both row and content level

This is a key Textual lesson: use explicit sizing logic when visual behavior matters.

### Tool Cards

Tool cards exist to summarize machine activity, not to become the whole visual language.

- Use neutral tonal surfaces first.
- Avoid obvious green washes and novelty tinting.
- Remove decorative borders.
- Keep internal padding compact.
- Keep spacing between cards modest but readable.
- Plain text output should look like terminal output, not like a syntax-highlight slab unless syntax is truly needed.

Tool cards must inherit the active theme.

That includes:

- card surface
- card border
- metadata text
- nested code surfaces
- syntax render backgrounds

If a code or YAML panel appears as an alien white or generic gray slab, the bug is usually in the renderable background, not the outer card shell.

Fix the renderable, not only the container.

### System and Special Cards

System, warnings, plans, and change-review elements may use contained surfaces because they represent non-conversational structures.

Even then:

- prefer muted surfaces
- keep padding tight
- keep labels compact

---

## 7. Spacing Rules

Spacing is the main structural tool in this UI, but it must be economical.

### General Principle

Terminal spacing should separate meaning, not decorate emptiness.

### Feed Spacing

- There should be a small top inset in the scrollable conversation area so the first message does not stick to the top edge.
- That inset should belong to the scrollable content, not to a fixed dead region outside the scroll.
- User messages need a small bottom gap before the next assistant/tool block.
- Tool cards need a little separation, but not enough to waste rows.

### Anti-Patterns

- Large margins used to fake alignment
- spacer rows that are not part of the scroll
- padding on every nested element at once
- independently styled gaps that compound unpredictably

When spacing feels wrong, inspect:

1. scroll container padding
2. row container margin
3. bubble/card padding
4. child body margin

Do not randomly change all four.

---

## 8. Sizing Rules

This section captures the most important Textual-specific lessons from the current work.

### Prefer Explicit Width for Important Elements

For user bubbles, “auto width until max width” should not be left to generic layout behavior.

Instead:

- compute width from visible content
- apply that width directly to the bubble widget
- clamp to a max width

This gives the intended behavior:

- short text creates a tight bubble
- longer text expands naturally
- long text wraps at a predictable maximum

### Avoid Over-Reliance on Shared Card Components

A generic shared card function is fine for:

- tool summaries
- plan cards
- notes
- system messages

It is not always fine for:

- user bubbles
- empty states
- any element with special alignment or width behavior

If an element keeps fighting the shared abstraction, split it into its own path.

### Height Rules

- Any action row containing tall buttons must have enough height for the labels to render.
- If content appears clipped, check parent row height before changing child styling.
- When a thing visually “disappears,” suspect sizing or alignment first.

---

## 9. Empty State Rules

The empty state must feel intentional, not like a default placeholder.

- Center the whole composition, not just its container.
- Keep copy minimal.
- Remove helper lines that repeat obvious behavior.
- If using an ASCII mark, center the mark itself, not only the wrapper.
- The empty state should not fight the composer or consume useful feed space once content exists.

The current preferred pattern is:

- legacy `iTE` mark
- one-line welcome
- no workspace path in the empty state
- no extra helper rows

---

## 10. Emoji and Iconography

Emoji are allowed, but they are functional, not decorative.

### Good Uses

- shell state
- attachments
- save/write actions
- tests
- git operations
- warnings and failures

### Bad Uses

- childish success icons
- overly cheerful icons in serious flows
- using emoji where a quiet geometric symbol is cleaner

If an emoji makes the interface feel unserious, replace it.

---

## 11. Color Rules for State

Color should communicate operational meaning fast.

### Success

- Use a restrained success tone.
- Avoid loud mint boxes.
- Success should feel calm and confirmed, not celebratory.

### Running

- Running states should feel live but neutral.
- Prefer subtle tonal lift over a bright status tint.

### Warning / Destructive

- Warm amber is better than bright red for most terminal workflows.
- Reserve harsher warning tones for real failure states.

### Selection

- Selected tabs, active routes, and focus states can use a cooler slate-blue.
- Keep this distinct from success.
- Selection treatment must still come from the active theme rather than a fixed blue.

---

## 12. Syntax, Code, and Dense Data

### Syntax Rule

Syntax highlighting and code surfaces are separate concerns.

- The code surface background must follow the active Textual theme.
- The syntax token palette may follow a dark or light syntax theme selected from theme polarity.
- Do not assume the Textual theme name is itself a valid Rich / Pygments syntax theme.

Current implementation rule:

- derive the syntax theme from active theme polarity unless a concrete syntax theme exists
- inject the code background explicitly from current theme tokens
- when a light theme makes source previews unreadable, prefer a theme-safe plain line-numbered rendering over faint syntax colors

If code rendering looks wrong:

1. check the code background token source
2. check whether the syntax renderer is using a real syntax theme
3. check the outer TCSS surface only after those two

### Theme Change Rule

Changing the app theme must update both:

- live widget chrome driven by TCSS
- already-rendered Rich renderables in the conversation

If only the shell updates, old tool cards may stay frozen with stale low-contrast colors.

So when the theme changes:

- rerender completed tool cards
- rerender other cached Rich surfaces that carry old colors
- refresh composer overlays and empty-state renderables

Theme switching is not complete until historical transcript surfaces repaint too.

### Dense Data

Change review is a high-density workflow and should respect terminal economics.

- Prioritize line clarity over ornament.
- Keep action rows readable and unclipped.
- Use compact metadata.
- Let the preview breathe horizontally.
- Avoid decorative framing around every subsection.

If a dense surface looks “amateur,” check:

- whether borders are doing too much
- whether tinting is too loud
- whether spacing is wasting rows
- whether labels are clipped

### Scrollbars

Textual scrollbars are terminal-cell based, not browser-pixel based.

- `scrollbar-size-vertical: 1` is the smallest practical visible vertical scrollbar.
- `scrollbar-size-horizontal: 1` is the smallest practical visible horizontal scrollbar.
- Setting either value to `0` hides that scrollbar.
- A horizontal scrollbar at size `1` can still look visually thick because one terminal row is a full character cell tall.
- Do not chase sub-cell scrollbar sizing; terminals do not provide that level of control.
- If a horizontal scrollbar still feels heavy at size `1`, prefer reducing horizontal overflow or softening scrollbar colors rather than trying fractional sizing.

Scrollbar sizing should be global by default so the chat feed, thread nav, change review, aside panel, and nested command-card scroll areas feel consistent. Override only when a specific widget intentionally hides or changes a scrollbar.

---

## 13. Modal Rules

Modal screens are a distinct interaction layer and must behave consistently.

### Modal Contract

- Modal screens are centered.
- The background behind them remains visible through a scrim.
- The scrim should be theme-driven.
- The modal shell should use theme tokens, not legacy dark literals.
- Internal picker tables must also be themed; the shell alone is not enough.

### Picker Rule

Picker modals such as:

- attach
- branch
- model
- theme
- session resume

should share the same structural model:

- centered modal shell
- title
- helper copy
- themed list / table surface
- aligned action row

If a new picker is added, it should be implemented as a native modal using the same structure rather than inventing a one-off surface.

### DataTable Rule

If a modal contains a `DataTable`, the table must be styled explicitly.

At minimum, theme:

- header
- odd/even rows
- cursor row
- header cursor
- surrounding list surface

Otherwise the table will keep default widget styling and visually break the modal.

### Commit Modal Rule

The commit modal now follows the same token rules as other modals:

- shell from `$surface` and `$border`
- labels from `$foreground-muted`
- primary actions from `$primary`
- success actions from `$success`
- cancel from `$panel`

---

## 14. Slash Palette and Composer Overlays

The slash palette is part of the composer control surface.

It must follow the active theme like any other overlay.

### Slash Palette Rule

- Palette shell uses theme tokens.
- Selected row uses theme-driven selection colors.
- Descriptions use muted text.
- It should never carry a fixed dark palette independent of the current theme.

### Slash Command Rule

Commands that map to native UI flows should appear in slash suggestions and open native in-app controls.

Examples:

- `/branch`
- `/attach`
- `/model`
- `/theme`

`/theme` belongs in this set. Theme switching is an in-app interaction, not a hidden palette-only behavior.

---

## 15. Notifications and Persistence

`iTE` now has two notification classes and they serve different purposes.

### Transient Notices

These are bottom-right notifications.

Use them for:

- theme changed
- git operation succeeded
- setup completed
- queue / retry / shift confirmations
- screenshot saved
- copy-to-clipboard confirmations
- other one-shot acknowledgements

These should not clutter the conversation transcript.

### Persistent System Cards

These stay in chat.

Use them for:

- actual errors
- important durable workflow state
- information the user should still see when reopening the thread later

Do not use persistent system cards for disposable confirmations.

If a user returns to the session later and the item would feel like noise, it should have been a transient notice.

---

## 16. Implementation Rules

These files are the source of truth for the current Textual UI:

- `src/ite/ui/reup/reup.tcss`
- `src/ite/ui/reup/app.py`
- `src/ite/ui/reup/composer_views.py`
- `src/ite/ui/reup/change_views.py`
- `src/ite/ui/reup/change_tree.py`
- `src/ite/ui/reup/tool_views.py`
- `src/ite/ui/reup/modals.py`

When changing the UI:

1. prefer the smallest structural change that fixes the behavior
2. avoid speculative restyling while fixing a layout bug
3. verify against the actual view state that broke
4. keep user-message, assistant-message, and tool-card paths conceptually separate
5. prefer active-theme tokens over ad hoc literals
6. if a renderable and a widget both control color, verify both layers
7. do not add a new picker or overlay without checking how the existing native pickers are built

---

## 17. Regression Checklist

Before considering a Textual UI change complete, check:

- Does the feed still maximize vertical space?
- Is the session strip hidden when not needed?
- Does the composer still keep its bottom action rail?
- Do user bubbles remain visible?
- Do user bubbles size to content before clamping?
- Is the first feed item offset from the top as part of the scroll area?
- Are tool action labels fully visible?
- Are tool cards compact and border-light?
- Did any accent color drift too bright or too green?
- Did spacing improve readability without wasting rows?
- Does the active palette theme visibly tint the app beyond only startup light/dark selection?
- Do syntax/code surfaces follow the active theme background?
- Do light-background themes still meet a readable contrast floor for body text, metadata, and semantic accents?
- Do picker modals center correctly with a visible background scrim?
- Do picker tables inherit the current theme instead of default `DataTable` styling?
- Does the slash palette follow the active theme?
- Do one-shot confirmations appear as transient notices instead of polluting chat history?
- After changing theme, do already-rendered tool cards repaint instead of keeping stale colors?

---

## 18. Summary

The main lesson is simple:

Designing `iTE` well in Textual means respecting terminal space, making structure explicit, and refusing web-UI habits that do not translate.

If something important depends on layout:

- encode it in the widget model
- keep styling restrained
- verify it in the actual running flow

That is the standard for future `iTE` UI work.
