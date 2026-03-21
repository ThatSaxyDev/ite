# Design System Strategy: Terminal Revamp

## 1. Overview & Creative North Star
**Creative North Star: The Monolith Console**

Traditional terminal environments are often fragmented—white text on a flat black void. This design system reimagines the developer workspace as a singular, high-fidelity "Monolith." We are moving away from the "grid of boxes" to an editorial-grade interface that uses deep tonal layering and sophisticated typography to prioritize information. 

By leveraging intentional asymmetry and high-contrast typography scales, we create a signature experience that feels less like a basic tool and more like a premium command center. The visual language is defined by the tension between the raw efficiency of code (Monospace) and the authoritative elegance of modern UI (Space Grotesk).

---

## 2. Colors
The palette is built on a foundation of deep charcoals and slates, using vibrant, high-saturation accents to pierce the dark theme.

### Tonal Foundations
- **Background:** `#131315` (The infinite void)
- **Surface (Neutral):** Using `surface_container` tiers to define depth.
- **Accents:** 
  - **Primary (Success/Action):** `#4edea3` (Emerald)
  - **Secondary (Info):** `#b7c8e1` (Slate Blue)
  - **Tertiary (Warning):** `#ffb95f` (Amber)

### The "No-Line" Rule
Standard 1px borders are strictly prohibited for sectioning. Visual boundaries must be achieved through:
1. **Background Shifting:** A `surface_container_low` sidebar sitting directly against a `surface` background.
2. **Tonal Transitions:** Defining logic blocks by shifting from `surface_container` to `surface_container_high`.

### Glass & Gradient Implementation
To avoid a flat "template" look, floating command palettes and overlays should utilize a **Glassmorphic** approach:
- Use `surface_variant` at 60% opacity with a `20px` backdrop-blur.
- Apply a subtle linear gradient to main CTAs (e.g., transitioning from `primary` to `on_primary_container`) to add "visual soul" and dimension.

---

## 3. Typography
We employ a dual-font strategy to separate content (code) from container (UI).

- **The Editorial UI (Space Grotesk):** Used for Headlines and Display styles. Its geometric, slightly quirky character provides an "avant-garde" tech feel.
- **The Functional Interface (Inter):** Used for labels, titles, and body text. High legibility, neutral tone.
- **The Data Layer (Monospace):** (Referencing the developer's request) High-quality mono fonts are used for all terminal output and code snippets.

### Scale Highlights
- **Display-LG:** `3.5rem` / Space Grotesk. For high-level workspace status.
- **Headline-SM:** `1.5rem` / Space Grotesk. For primary section headers.
- **Label-MD:** `0.75rem` / Inter. For metadata and status tags.

---

## 4. Elevation & Depth
In this design system, depth is a function of light and layering, not structural lines.

### The Layering Principle
Hierarchy is achieved by "stacking" container tiers.
- **Base Layer:** `surface` (#131315)
- **Primary Layout Blocks:** `surface_container_low` (#1C1B1D)
- **Interactive Cards/Elements:** `surface_container_high` (#2A2A2C)

### Ambient Shadows
When an element must float (e.g., a command palette), use an **Ambient Shadow**:
- **Blur:** 32px to 64px.
- **Opacity:** 6% of the `on_surface` color.
- **Offset:** Vertical only (4px - 8px) to mimic a top-down light source.

### The "Ghost Border" Fallback
If a border is required for extreme accessibility cases, use the **Ghost Border**:
- Color: `outline_variant` (#45464D)
- Opacity: **Max 15%**. It should be felt, not seen.

---

## 5. Components

### Primary Buttons
- **Style:** High-saturation `primary` (#4EDE3A) background with `on_primary` (#003824) text.
- **Shape:** `DEFAULT` (0.5rem/8px) roundedness.
- **Interaction:** On hover, shift to `primary_fixed` for a "glow" effect.

### Code Blocks & Terminal Output
- **Background:** `surface_container_lowest` (#0E0E10).
- **Padding:** `spacing[5]` (1.1rem) to give code room to breathe.
- **Success State:** Left-hand accent bar using `primary` (#4EDE3A) at 4px width.

### Command Palette (Floating)
- **Background:** Glassmorphic `surface_container_highest` with backdrop-blur.
- **Shadow:** Large ambient shadow.
- **Search Input:** Ghost border (10% opacity) with `title-md` typography.

### Chips & Tags
- **Success:** `primary_container` background with `on_primary_container` text.
- **Warning:** `tertiary_container` background with `on_tertiary_container` text.
- **Shape:** `full` (pill-shaped) for distinct contrast against square terminal blocks.

---

## 6. Do's and Don'ts

### Do:
- **Use Intentional Asymmetry:** Align terminal output to a different grid than the UI controls to create visual interest.
- **Embrace White Space:** Use the `spacing[8]` (1.75rem) and `spacing[10]` (2.25rem) tokens to separate major logic blocks instead of dividers.
- **Layer Surfaces:** Always place lighter containers on darker backgrounds to signify "lift."

### Don't:
- **Don't use 100% white text:** Always use `on_surface_variant` (#C6C6CD) for secondary text to reduce eye strain in dark mode.
- **Don't use 1px Solid Borders:** Never use a high-contrast line to separate the sidebar from the main terminal. Use a background color shift.
- **Don't settle for flat colors:** Use the `surface_tint` to apply a 2% color overlay to surfaces to keep the dark theme from feeling "dead" or muddy.