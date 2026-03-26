# Skills

`ite` supports interoperable `SKILL.md` bundles modeled after the broader Agent Skills ecosystem.

## Shared vs Local

- Shared project skills: `.agents/skills/<skill-name>/SKILL.md`
- Local machine overrides: `.ite/skills/<skill-name>/SKILL.md`

Use `.agents/skills` for skills you want committed and shared across a team. Use `.ite/skills` only for private overrides because `.ite/` is commonly gitignored.

## Trust Model

Shared project skills can contain arbitrary instructions. To avoid silently loading repo-provided skills into the prompt, `ite` treats project skill roots as untrusted until you explicitly trust the workspace.

- Trust the current workspace: `/skills trust`
- Remove trust and clear active project skills: `/skills untrust`

Local overrides in `.ite/skills` and global skill roots are treated as trusted by default.

## Compatibility Roots

`ite` discovers skills from these roots, with later paths overriding earlier ones when the same skill identifier appears:

- `~/.agents/skills`
- `~/.claude/skills`
- `~/.codex/skills`
- `~/.cursor/skills`
- `~/.gemini/skills`
- `~/.opencode/skills`
- `~/.kiro/skills`
- `~/.pi/skills`
- `~/.config/ite/skills`
- `<project>/.agents/skills`
- `<project>/.claude/skills`
- `<project>/.codex/skills`
- `<project>/.cursor/skills`
- `<project>/.gemini/skills`
- `<project>/.opencode/skills`
- `<project>/.kiro/skills`
- `<project>/.pi/skills`
- `<project>/.ite/skills`

This means public “universal” skill packs can usually work without conversion as long as one of their supported roots is copied into the project.

## Minimum Skill Format

```md
---
name: critique
description: Evaluate design effectiveness from a UX perspective.
---

Skill instructions go here.
```

Required frontmatter:

- `name`
- `description`

Supported optional frontmatter:

- `aliases`
- `user-invocable`
- `argument-hint`
- `tags`
- `version`
- `author`
- `homepage` or `url`

Unknown frontmatter is preserved and ignored unless a later feature uses it .

## References

If a skill folder contains `reference/` or `references/`, `ite` records those files as skill references and surfaces them in `/skills show <name>`.
When a skill is active, `ite` also loads bounded excerpts from referenced files into the prompt context, prioritizing references explicitly mentioned in the skill instructions.

Example:

```text
.agents/skills/frontend-design/
  SKILL.md
  reference/
    typography.md
    motion-design.md
```

## Commands

- `/skills`
- `/skills help`
- `/skills show <name>`
- `/skills use <name>`
- `/skills drop <name>`
- `/skills clear`
- `/skills trust`
- `/skills untrust`
- `/skills add <path|owner/repo|git-url> [--global|--local]`

The `skills` tool exposes the same basic operations to the model.

## Installing Skill Packs

`/skills add` accepts:

- a single skill directory containing `SKILL.md`
- a folder of skills
- a universal pack root that contains one of the known `*/skills/` roots
- a git URL
- a GitHub shorthand like `owner/repo`

Examples:

```text
/skills help
/skills add ~/Downloads/impeccable-style-universal
/skills add ~/Downloads/critique
/skills add openai/agent-skills
/skills add https://github.com/openai/agent-skills.git
/skills add ~/Downloads/impeccable-style-universal --global
```

Default destination is `<project>/.agents/skills`.

## Bundled First-Party Skills

`ite` currently vendors these first-party skills in the shared project root so they ship with the app and are discoverable out of the box:

- `docx`
- `pdf`

These are the curated, product-owned skills. Other compatible skills can still be installed from local packs or repos with `/skills add`.
