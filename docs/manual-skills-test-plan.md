# Manual Skills Compatibility Test Plan

This guide is for manually validating that `ite` skills work against the broader ecosystem, not just one specific skill pack.

It is written from the operator side, not the unit-test side.

Use it to validate:

- generic `SKILL.md` compatibility
- import/install behavior across multiple repo shapes
- workspace trust gating
- activation and deactivation
- frontmatter handling
- reference-aware behavior
- compatibility roots
- local override precedence
- session persistence
- failure handling

Impeccable is included as one useful fixture, but it is not the product definition.

---

## Test Workspace

Primary workspace:

```bash
cd /Users/kiishidavid/Documents/Dev/Projects/ite
ite
```

Helpful local fixture already present:

```text
/Users/kiishidavid/Documents/Dev/Projects/ite/impeccable-style-universal
```

Start a fresh thread before each major scenario:

```text
/new
```

---

## Core Compatibility Contract

`ite` should accept all of these shapes:

1. Single-skill directory
2. Multi-skill flat directory
3. Universal pack with supported `*/skills/` roots
4. Compatibility-root-only packs like `.codex/skills` or `.cursor/skills`
5. Skills with unknown frontmatter
6. Skills with no references
7. Skills with `reference/` or `references/`
8. Mixed-validity packs where some skills are malformed and others are valid

`ite` should not assume:

- Impeccable-specific skill names
- Impeccable-specific frontmatter
- that every skill uses references
- that `.agents/skills` is the only root in a pack

---

## Product Expectations

The current `ite` skills product should behave like this:

- shared project skills live in `.agents/skills`
- `.ite/skills` is only for local/private overrides
- project-provided shared skills are blocked until trusted
- global roots and local overrides are trusted by default
- active skills influence behavior
- only active skills should contribute instruction context
- referenced files should help active skills without exploding prompt size

---

## Fixture Matrix

Use at least these repo shapes during validation:

### Fixture A: Single Skill Directory

Example shape:

```text
single-skill/
  SKILL.md
```

### Fixture B: Multi-Skill Flat Directory

Example shape:

```text
flat-pack/
  critique/
    SKILL.md
  planner/
    SKILL.md
```

### Fixture C: Universal Multi-Agent Pack

Example:

```text
/Users/kiishidavid/Documents/Dev/Projects/ite/impeccable-style-universal
```

### Fixture D: Compatibility-Root-Only Pack

Example shape:

```text
compat-pack/
  .codex/
    skills/
      reviewer/
        SKILL.md
```

### Fixture E: Mixed-Validity Pack

Example shape:

```text
mixed-pack/
  good-skill/
    SKILL.md
  bad-skill/
    SKILL.md   # malformed or invalid
```

---

## Scenario 1: Empty-State UX

Before running this scenario, make sure the project does not currently have installed shared skills in:

```text
.agents/skills
```

Prompt:

```text
/skills
```

Expected:

- clear empty-state message
- message recommends `.agents/skills` for shared skills
- `.ite/skills` is described as local override only
- no crash or noisy error output

---

## Scenario 2: Import a Single Skill Directory

Use Fixture A.

Prompt:

```text
/skills add /path/to/single-skill
```

Expected:

- install succeeds
- destination defaults to project `.agents/skills`
- detected source root is reported
- the installed skill appears in `/skills`

Then:

```text
/skills show <skill-name>
```

Expected:

- `name` and `description` render correctly
- instructions are shown

---

## Scenario 3: Import a Flat Multi-Skill Directory

Use Fixture B.

Prompt:

```text
/skills add /path/to/flat-pack
```

Expected:

- all valid child skills install
- multiple skills appear in `/skills`
- no assumption that the source must be a universal pack

---

## Scenario 4: Import a Universal Pack

Use Fixture C.

Prompt:

```text
/skills add /Users/kiishidavid/Documents/Dev/Projects/ite/impeccable-style-universal
```

Expected:

- install succeeds
- one supported root is detected automatically
- multiple skills are installed
- `/skills` shows a broad set of discovered skills

This scenario proves compatibility with a real-world pack, but should not be treated as the only supported format.

---

## Scenario 5: Import a Compatibility-Root-Only Pack

Use Fixture D.

Prompt:

```text
/skills add /path/to/compat-pack
```

Expected:

- install succeeds even if the pack only contains `.codex/skills`, `.cursor/skills`, or another supported compatibility root
- no conversion step is required

---

## Scenario 6: Trust Gate

Prompt sequence:

```text
/skills untrust
/skills
/skills use <shared-project-skill>
/skills show <shared-project-skill>
```

Expected:

- project skills are blocked after untrust
- activation is refused with a clear trust instruction
- `/skills show ...` still displays metadata and instructions
- blocked trust state is visible
- active project skills are cleared on untrust

Then trust the workspace:

```text
/skills trust
/skills use <shared-project-skill>
```

Expected:

- trust succeeds
- blocked project skills become activatable

---

## Scenario 7: Frontmatter Compatibility

Use at least one skill with common optional metadata and one skill with unknown metadata.

Prompt:

```text
/skills show <skill-name>
```

Expected:

- `name` and `description` are visible
- `aliases` work for lookup
- `user-invocable` appears if present
- `argument-hint` appears if present
- `version`, `author`, `homepage`, and `tags` appear if present
- unknown frontmatter does not break display or import

---

## Scenario 8: Reference Discovery

Use a skill with `reference/` or `references/`.

Prompt sequence:

```text
/skills show <reference-backed-skill>
/skills use <reference-backed-skill>
```

Expected:

- `show` output lists reference files
- the skill activates successfully
- the CLI does not dump the full reference corpus to the terminal

---

## Scenario 9: Reference-Aware Behavior

With the reference-backed skill active, ask a task where those references should matter.

Prompt:

```text
Use the active skill if relevant. Review this project and tell me the top issues using the skill's standards.
```

Expected:

- answer reflects deeper skill guidance
- referenced material appears to influence the output
- response stays bounded and readable

---

## Scenario 10: Behavioral Delta

Prompt sequence:

```text
/skills clear
Review this project and tell me what is weak.
/skills use <skill-name>
Review this project and tell me what is weak.
```

Expected:

- first answer is more generic
- second answer is materially shaped by the skill
- behavior change is noticeable, not placebo-level

---

## Scenario 11: Multi-Skill Stack

Activate two compatible skills.

Prompt sequence:

```text
/skills use <skill-a>
/skills use <skill-b>
Use active skills if relevant. Audit this project and recommend what to improve first.
```

Expected:

- output combines both skills coherently
- no duplicated nonsense or obvious prompt conflict
- result remains prioritized and readable

---

## Scenario 12: Deactivation

Prompt sequence:

```text
/skills drop <skill-a>
Use active skills if relevant. Audit this project and recommend what to improve first.
```

Expected:

- dropped skill no longer influences the result
- behavior changes accordingly

---

## Scenario 13: Local Override Precedence

Create a local override:

```text
.ite/skills/<skill-name>/SKILL.md
```

Make its instructions clearly different from the shared version.

Then run:

```text
/skills
/skills show <skill-name>
/skills use <skill-name>
```

Expected:

- local override wins over shared project skill
- source indicates local override
- activated behavior follows the local instructions

---

## Scenario 14: Compatibility Roots In Place

Copy valid skills into one or more supported roots inside the project:

- `.codex/skills`
- `.cursor/skills`
- `.gemini/skills`
- `.opencode/skills`
- `.claude/skills`

Then run:

```text
/skills
```

Expected:

- skills are discovered without conversion
- source labels reflect the compatibility roots
- parsing behavior is consistent across roots

---

## Scenario 15: Session Persistence

Prompt sequence:

```text
/skills use <skill-a>
/skills use <skill-b>
Use active skills if relevant. Give me a quick audit.
```

Then resume the thread using the normal session flow.

After resume:

```text
/skills
```

Expected:

- active skills remain active
- resumed prompts still reflect the active skill stack
- no silent loss of skill state

---

## Scenario 16: Install Variants

Test all of these:

```text
/skills add /path/to/pack --global
```

```text
/skills add /path/to/pack --local
```

```text
/skills add /path/to/single-skill-dir
```

Expected:

- `--global` installs to a global shared root
- `--local` installs to `.ite/skills`
- default installs to project `.agents/skills`
- success message reports destination and detected source root

Then test invalid flags:

```text
/skills add /path/to/pack --global --local
```

Expected:

- clear error telling the user to choose one destination

---

## Scenario 17: Mixed-Validity Packs

Use Fixture E.

Prompt:

```text
/skills add /path/to/mixed-pack
```

Expected:

- valid skills still install
- invalid skills are skipped or rejected safely
- no all-or-nothing failure unless the pack contains no usable skills at all

---

## Scenario 18: Failure Cases

Validate these failure paths:

- malformed `SKILL.md`
- invalid YAML frontmatter
- missing required frontmatter fields
- skill folder without `SKILL.md`
- binary file under `reference/`
- invalid install path

Example:

```text
/skills add /path/that/does/not/exist
```

Expected:

- failure is clear and contained
- no crash
- invalid skills are skipped safely

---

## Scenario 19: Prompt Bloat Sanity

Activate a skill with references and run several normal prompts.

Example:

```text
/skills use <reference-backed-skill>
Use active skills if relevant. Critique this project.
Use active skills if relevant. Suggest concrete fixes.
Use active skills if relevant. Summarize the priorities.
```

Expected:

- no obvious context explosion
- referenced content helps without swamping the response
- behavior remains stable across multiple turns

---

## Pass Criteria

The skills subsystem is ready for practical ecosystem use if all of the following are true:

- generic single-skill repos import cleanly
- flat multi-skill repos import cleanly
- universal packs import cleanly
- compatibility-root-only packs import cleanly
- project-provided skills are trust-gated
- trusted skills activate reliably
- active skills visibly change behavior
- referenced files materially improve skill quality
- compatibility roots work without conversion
- local overrides beat shared project skills
- active skills survive session resume
- mixed-validity packs degrade safely
- failure cases do not crash the product
- `/skills` is sufficient for a normal operator to understand what is happening

---

## Impeccable as a Fixture

The Impeccable universal pack is still a useful real-world validation target because it exercises:

- multi-root universal packaging
- multiple skills
- frontmatter like `user-invocable` and `argument-hint`
- reference-backed skills

But it should remain one fixture among several, not the only acceptance criterion.

---

## Current Known Boundary

This plan validates local-path imports only.

Current scope:

- `/skills add /path/to/pack`

Not yet implemented:

- network-backed install such as `skills add owner/repo`

If that is added later, extend this plan with transport, fetch, archive, and partial-download scenarios.
