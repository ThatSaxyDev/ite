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

---

## 12. Change Review and Dense Data

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

---

## 13. Implementation Rules

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

---

## 14. Regression Checklist

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

---

## 15. Summary

The main lesson is simple:

Designing `iTE` well in Textual means respecting terminal space, making structure explicit, and refusing web-UI habits that do not translate.

If something important depends on layout:

- encode it in the widget model
- keep styling restrained
- verify it in the actual running flow

That is the standard for future `iTE` UI work.
