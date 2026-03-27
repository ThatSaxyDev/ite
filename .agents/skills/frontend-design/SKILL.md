---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces with exceptional design quality. Use when the user asks to build, redesign, refine, review, or polish websites, landing pages, dashboards, apps, or components. The goal is real shipped UI with strong taste, not generic AI output.
---

This is iTE's flagship frontend design skill.

It should feel like what Impeccable was aiming for, but written for iTE: native workflow, native context assumptions, native paths, and strong implementation discipline.

## What This Skill Is For

Use this skill when the user wants:
- a new frontend surface designed and implemented
- an existing UI pushed from functional to excellent
- design critique with concrete next moves
- improvements to hierarchy, spacing, type, color, motion, responsiveness, or polish

The output should usually be working frontend code or concrete design changes, not abstract design theory.

## Context Gathering Protocol

Design work gets generic fast when context is thin. You MUST confirm design context before making meaningful visual decisions.

### Required context

Every frontend design task needs, at minimum:
- **Target audience**: who uses this product and in what context
- **Use case**: what job the interface helps them do
- **Tone**: how the product should feel

You may also need:
- brand references or anti-references
- accessibility constraints
- product maturity: MVP, polished release, flagship launch
- whether you are extending an existing design system or creating a fresh direction

### Gathering order

1. **Check the current request and loaded instructions first.**
   If the user already gave audience, goals, or tone, use that.
2. **Inspect the existing product.**
   Read the codebase, tokens, components, content patterns, and current UI language.
3. **Check saved project context.**
   Read `AGENTS.md` in scope and `.agents/design-context.md` if present.
4. **Ask only the smallest set of missing questions.**
   Do not run a generic brand questionnaire when the codebase already answers half of it.

### Critical rule

Do not invent audience, tone, or product posture when those choices materially affect the design.

---

## Existing Product vs New Surface

Choose one mode early.

### Mode 1: Existing Product

Use this when working inside an established app, site, or design system.

Rules:
- preserve the product's recognizable visual language unless the user asked for redesign
- improve clarity, quality, and distinctiveness without making the product feel like a different company
- reuse good existing patterns; remove weak ones
- solve system-level design problems before decorating isolated components

### Mode 2: New Surface

Use this when the user wants something new, bold, or intentionally reimagined.

Rules:
- commit to a strong point of view
- choose a memorable visual idea, not a safe template
- make the design feel authored rather than assembled
- keep the code maintainable even when the visuals are ambitious

---

## Design Direction

Before implementation, lock in a clear direction:
- **Purpose**: what this interface helps the user do
- **Tone**: refined, playful, editorial, technical, premium, raw, calm, energetic, etc.
- **Constraints**: framework, performance, accessibility, content density
- **Differentiation**: what makes this memorable instead of interchangeable

If you cannot summarize the direction in one short sentence, the direction is not ready.

## Frontend Aesthetics Guidelines

### Typography
Read `references/typography.md` when hierarchy, font choice, readability, or rhythm matter.

**DO**
- Use a clear type hierarchy with meaningful contrast
- Choose fonts with character when the product can support it
- Pair a strong display voice with a readable body voice, or use one excellent family well

**DON'T**
- Default to Inter, Roboto, Arial, Open Sans, or other invisible defaults when personality matters
- Use muddy scales where every size feels adjacent
- Use monospace as a lazy shortcut for "technical"

### Color & Theme
Read `references/color-and-contrast.md` when setting palettes, semantic color, or contrast strategy.

**DO**
- Use color with purpose: hierarchy, meaning, tone, wayfinding
- Prefer cohesive palettes with tinted neutrals
- Use modern color functions when the stack allows it

**DON'T**
- Default to purple-blue gradient branding
- Use gray text on colored backgrounds
- Use pure black or pure white as the main look when a tinted neutral would feel more intentional

### Layout & Space
Read `references/spatial-design.md` when fixing layout, grouping, density, or rhythm.

**DO**
- Create rhythm with varied spacing
- Use asymmetry and composition intentionally
- Let space create hierarchy before adding decorative effects

**DON'T**
- Wrap everything in cards
- Nest cards inside cards
- Repeat identical icon-heading-body grids without variation
- Center everything by default

### Motion
Read `references/motion-design.md` when adding transitions, entrances, or interaction feedback.

**DO**
- Use motion to explain state change and create delight
- Focus on one or two strong moments instead of many weak ones
- Respect reduced-motion preferences

**DON'T**
- Animate layout properties when transform or opacity will do
- Use bounce or elastic easing as default
- Scatter decorative motion everywhere

### Interaction
Read `references/interaction-design.md` when refining forms, controls, focus behavior, loading, or overlays.

**DO**
- Make interactions feel responsive and intentional
- Design real states: hover, focus, active, disabled, loading, error, success
- Use progressive disclosure when complexity exists

**DON'T**
- Make every action primary
- rely on hover for essential behavior
- leave empty, error, or loading states as afterthoughts

### Responsive
Read `references/responsive-design.md` when adapting layouts or controls across devices and input modes.

**DO**
- Adapt the interface for the context instead of just shrinking it
- think about touch, hover, keyboard, and density together
- ensure mobile feels designed, not amputated

### UX Writing
Read `references/ux-writing.md` when labels, errors, buttons, or empty states need work.

**DO**
- Make every word earn its place
- write labels that communicate action and meaning

**DON'T**
- repeat what the user can already see
- fill the UI with generic product-copy filler

---

## The AI Slop Test

This is a mandatory quality gate.

Ask:
- If someone saw this and heard "AI made it," would they immediately believe it?
- Does it rely on obvious 2024-2026 AI defaults?
- Is it visually safe instead of intentional?

Common tells to avoid:
- generic SaaS hero structures
- gradient text used as "impact"
- glowing dark dashboards by default
- decorative charts with no real purpose
- repeated cards with no compositional intelligence
- default font stacks with no typographic opinion

If the result feels interchangeable with dozens of AI-generated mockups, it is not done.

---

## Execution Modes

Choose the appropriate mode for the task.

### Build

When creating or redesigning UI:
- establish direction first
- implement real working code
- solve hierarchy, spacing, and interaction before decorative flourishes
- use the references selectively as needed

### Critique

When reviewing existing UI:
- start with whether it looks generic
- identify the 3-5 highest leverage design problems
- explain why each one matters
- give concrete direction, not vague taste commentary

### Polish

When doing a finishing pass:
- check alignment, spacing consistency, typography consistency, states, copy, motion, and responsiveness
- fix system-level issues before pixel-level ones
- use restraint; polish should sharpen the concept, not blur it

---

## Implementation Principles

- Ship real code, not just style notes.
- Match implementation complexity to the visual ambition.
- Prefer tokens or CSS variables for color, spacing, radius, shadow, and timing.
- Keep DOM structure lean; do not hide weak design under wrapper spam.
- Respect accessibility fundamentals: semantic HTML, contrast, keyboard use, visible focus, reduced motion.
- Ensure the UI survives real content, not just ideal placeholder strings.
- If working inside a framework, follow the local project conventions rather than imposing a new architecture.

## Review and Polish Checklist

Before finishing, verify:
- the primary action is obvious within seconds
- typography has clear hierarchy and good readability
- spacing has rhythm instead of uniform padding everywhere
- interactive states exist and feel intentional
- mobile layout still feels designed
- decorative elements reinforce the concept instead of compensating for weak structure
- the UI feels specific to the product, not generic to AI

## Output Expectations

Preferred output:
- implemented frontend code with strong visual quality

If the task is review-only, provide:
- anti-slop verdict
- overall impression
- what is working
- priority issues ordered by impact
- concrete fixes or next design moves

The standard is not "good for AI."
The standard is "good enough to ship with pride."

---

## Design Context Setup

If required design context is still missing after inspecting the request and codebase, gather it efficiently and persist it for future runs.

### Step 1: Explore

Before asking questions, scan:
- README and docs
- package/config files
- existing components and layout patterns
- brand assets
- CSS variables, tokens, fonts, and spacing systems

### Step 2: Ask only what is missing

Focus on the smallest useful set of questions:
- who is this for
- what should it feel like
- what should it explicitly not look like
- any must-use or must-avoid colors, references, or constraints

### Step 3: Write Design Context

Persist a reusable `## Design Context` section to `.agents/design-context.md`.

If the user wants the context auto-loaded in future runs, also append or update the same section in the relevant `AGENTS.md`.
