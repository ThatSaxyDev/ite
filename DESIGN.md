# Design System Strategy: iTE Terminal UI

## 1. North Star
**Creative North Star: The iTE Command Console**

`iTE` should feel like a premium command room inside the terminal, not a stack of generic dark panels. The UI needs editorial hierarchy, deliberate asymmetry, and deep tonal layering so the workspace reads as one coherent instrument.

This is a terminal product, so the system must be written for terminal reality:

- We do **not** rely on true blur, gradients, arbitrary fonts, or pixel-perfect web affordances.
- We create depth with **surface shifts, bold typographic contrast, spacing, and restrained accent color**.
- We avoid the usual "blue box on dark gray box" dashboard look.

The result should feel quiet, expensive, and sharply legible while a user is reading diffs, following tool activity, or composing the next turn.

---

## 2. Palette

### Core Surfaces
- **Canvas:** `#131315`
- **Surface Low:** `#1c1b1d`
- **Surface Mid:** `#232327`
- **Surface High:** `#2a2a2c`
- **Code Well / Deep Recess:** `#0e0e10`

### Accents
- **Primary / Success / Go:** `#4edea3`
- **Secondary / Informational:** `#b7c8e1`
- **Warning / Risk / Destructive:** `#ffb95f`

### Text
- **Primary text:** `#f2f5f8`
- **Secondary text:** `#c6c6cd`
- **Muted text:** `#8c93a1`

### Ghost Border
- **Fallback edge:** `#45464d` at very low opacity

### The Terminal "No-Line" Rule
The default separation pattern is **not** a bright 1px divider. In `iTE`, hierarchy should come from:

1. Surface shifts between canvas and container tiers.
2. Changes in padding density.
3. Accent color reserved for state and intent.

Ghost borders are allowed only for:

- floating composer surfaces
- command palettes
- modals
- code wells when readability needs a frame

---

## 3. Typography and Hierarchy

The terminal gives us one real type family: monospace. That means hierarchy must come from:

- bold versus regular weight
- all-caps editorial kickers
- wide spacing between logic groups
- restrained line length
- contrasting open versus boxed content

### Hierarchy Rules
- **Kickers:** short all-caps labels like `AI TERMINAL`, `COMPOSE`, `WORKSPACE`
- **Primary title:** current thread title
- **Metadata rails:** muted, compact, right-aligned or inline
- **Terminal content:** never over-decorated; clarity wins

---

## 4. Layout Mapping for iTE

### Topbar
The topbar is the identity anchor.

- A compact `iTE` mark sits at the far left.
- A small kicker and the current thread title create the editorial stack.
- Workspace, model, plan state, thread count, and git branch live in a right-aligned metadata rail.
- `/changes` and `/aside` are compact action pills, not loud buttons.

### Session Strip
Session tabs live beneath the topbar as pill-shaped tokens.

- Inactive tabs sit on `surface_mid`.
- Active tabs use a cooler raised tone.
- Live tabs use a warmer or greener active tone depending on state.

### Conversation Well
The conversation area stays mostly open on the canvas.

- Assistant output should feel integrated into the canvas, not trapped in heavy cards.
- User messages should be offset and boxed on a darker surface to create asymmetry.
- System, plan, workboard, and tool messages can use contained cards when needed.

### Composer Dock
The composer is the floating control surface.

- It should feel slightly elevated from the base canvas.
- It includes a small `COMPOSE` kicker, the prompt area, the inline status rail, and the slash palette.
- The slash palette is the glassiest element in the shell.

### Side Panels
The change review and aside panels are tonal slabs.

- They should read as neighboring surfaces, not panels split off by bright borders.
- Use spacing and background shift to show separation.

### Footer
The footer remains functional and low-contrast. It should support the interface, not compete with it.

---

## 5. Component Rules

### Session Tabs
- Pill-shaped
- No harsh outlines
- Stronger fill on active
- Distinct live-state fill for running work

### User Cards
- Darker surface than the canvas
- Offset to the right
- Compact and intentional

### Assistant Messages
- Mostly open
- Minimal framing
- Code fences and block quotes may use recessed wells

### Emoji Use
- High-signal emoji iconography is allowed.
- Keep emoji where it improves scanability fast: attachments, shell status, success/failure, tests, git actions.
- Don’t remove useful emoji just to make the UI feel more austere.

### Tool Cards
- Tinted by state:
  - running: neutral elevated surface
  - success: green-tinted surface
  - recoverable/warning: amber-tinted surface
  - failure: warm, darker warning surface

### Command Palette
- Elevated surface with ghost border
- Selected row uses the primary accent
- Descriptions stay muted

### Change Review
- File tree on a darker inset surface
- Preview on the base canvas
- Stage and commit actions use success/info tones
- Discard actions use warning tone

### Modals
- Centered elevated surfaces
- No loud purple defaults
- Primary confirm actions use emerald
- Secondary progression actions can use slate

---

## 6. Motion and Live State

Motion in terminal is sparse by necessity, so it must mean something.

- Spinners should be subtle and elegant.
- Running states should "glow" through color and placement, not noise.
- Live shell sessions should feel active without becoming visually loud.

---

## 7. Do / Don't

### Do
- Use asymmetry between user bubbles and assistant output.
- Use spacing to separate major blocks instead of divider lines.
- Keep assistant content breathable.
- Reserve accent color for state transitions and calls to action.
- Let the composer feel like a dedicated control surface.

### Don't
- Don’t reintroduce bright default blue or purple accents as the main theme.
- Don’t turn the whole interface into boxed cards.
- Don’t use high-contrast lines to split the shell into regions.
- Don’t make metadata compete with the primary thread title.
- Don’t flatten every state into the same neutral gray.

---

## 8. Implementation Notes

This system maps directly onto the current Textual implementation for `iTE`:

- `src/ite/ui/reup/reup.tcss`
- `src/ite/ui/reup/app.py`
- `src/ite/ui/reup/composer_views.py`
- `src/ite/ui/reup/change_views.py`
- `src/ite/ui/reup/change_tree.py`
- `src/ite/ui/reup/tool_views.py`
- `src/ite/ui/reup/modals.py`

`src/ite/ui/reup/` is the implementation path, not the product name.
