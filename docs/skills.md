# Skills

Skills are instruction bundles that extend iTE's capabilities on specific tasks.

## How Skills Work

Skills are interoperable `SKILL.md` bundles. They can be:

- **Global**: Installed in `~/.config/ite/skills/` (always trusted)
- **Project**: Installed in `.agents/skills/` or `.ite/skills/` (require trust)

## Compatibility

iTE discovers skills from common agent roots:

- `~/.agents/skills`, `~/.codex/skills`, `~/.cursor/skills`
- `~/.claude/skills`, `~/.gemini/skills`, `~/.opencode/skills`
- `<project>/.agents/skills`, `<project>/.codex/skills`, etc.

Skills designed for other agents (Claude Code, Codex, OpenCode) often work without modification.

## Commands

```
# List available skills
/skills

# Inspect a skill
/skills show <name>

# Activate a skill
/skills use <name>

# Install a skill pack
/skills add <path>
/skills add owner/repo      # GitHub shorthand
/skills add <git-url>     # Git repository

# Trust project skills
/skills trust

# Untrust and clear project skills
/skills untrust

# Clear all active skills
/skills clear
```

## Trust Model

- **Global skills**: Trusted by default
- **Project skills**: Require explicit trust with `/skills trust`

This prevents malicious projects from silently injecting harmful instructions.

## Bundled Skills

iTE includes these first-party skills:

- `docx` — Create and edit Microsoft Word documents
- `pdf` — Read and extract text from PDFs

---

[Learn about MCP →](mcp.md)
