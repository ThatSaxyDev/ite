# Three-Tier AGENTS.md System Design

## Overview

Implement a hierarchical AGENTS.md system with three levels of precedence:

1. **Global** (`~/.config/ite/AGENTS.md`) - User preferences across all projects
2. **Personal Project** (`.ite/AGENTS.md`) - Project-specific personal preferences (not committed)
3. **Team Project** (`AGENTS.md` at root) - Shared team guidelines (committed to git)

## Precedence Rules

**Loading Order (least to most specific):**
1. Global AGENTS.md files (`~/.config/ite/`, `~/.agents/`)
2. Personal project `.ite/AGENTS.md`
3. Team project `AGENTS.md` (root level)
4. AGENTS.override.md at any level takes precedence over AGENTS.md at that same level

**Merge Strategy:**
- Later files in the list override earlier files (most specific wins)
- 32 KiB combined size limit (existing behavior preserved)
- Files annotated with `<!-- From: {path} -->` comments

## File Structure Changes

### `/init` Command Updates

**New Flags:**
```
/init                 # Creates team AGENTS.md at root (existing behavior)
/init --personal      # Creates personal AGENTS.md in .ite/
/init --global        # Creates global AGENTS.md in ~/.config/ite/
/init --force         # Force overwrite existing (works with all tiers)
```

**Flag Combinations:**
- `--personal --force` - Overwrite personal AGENTS.md
- `--global --force` - Overwrite global AGENTS.md
- `--force` alone - Overwrite team AGENTS.md (backward compatible)

### Generation Strategy by Tier

| Tier | Command | Data Source | Prompt Strategy |
|------|---------|-------------|-----------------|
| Team | `/init` | Code scanning | Analyze codebase, extract conventions |
| Personal | `/init --personal` | User input | Ask: "What personal preferences for this project?" |
| Global | `/init --global` | User input | Ask: "What are your global coding preferences?" |

## Implementation Plan

### Phase 1: Loader Updates (`loader.py`)

**File:** `src/ite/config/loader.py`

Modify `_get_agents_md_files(cwd: Path)`:

```python
def _get_agents_md_files(cwd: Path) -> list[tuple[Path, str]]:
    """
    Three-tier loading:
    1. Global: ~/.config/ite/AGENTS.md or ~/.agents/AGENTS.md
    2. Personal: .ite/AGENTS.md (project-specific personal prefs)
    3. Team: AGENTS.md at root (shared)
    """
    current = cwd.resolve()
    files: list[tuple[Path, str]] = []
    
    # Tier 1: Global
    global_path = get_data_dir()
    files.extend(_get_agents_md_at_path(global_path))
    
    # Check alternative global location ~/.agents/
    home = Path.home()
    alt_global_path = home / ".agents"
    if alt_global_path != global_path:
        alt_files = _get_agents_md_at_path(alt_global_path)
        for f in alt_files:
            if f[0] not in [existing[0] for existing in files]:
                files.append(f)
    
    # Walk from root down to cwd
    paths_to_check: list[Path] = []
    while current != current.parent:
        paths_to_check.append(current)
        current = current.parent
    paths_to_check.append(current)
    
    for path in reversed(paths_to_check):
        # Tier 2: Personal (.ite/AGENTS.md)
        personal_ite_dir = path / WORKSPACE_DIR_NAME
        if personal_ite_dir.is_dir():
            files.extend(_get_agents_md_at_path(personal_ite_dir))
        
        # Tier 3: Team (AGENTS.md at root)
        files.extend(_get_agents_md_at_path(path))
    
    return files
```

### Phase 2: `/init` Command Updates (`init.py`)

**File:** `src/ite/commands/init.py`

Add argument parsing for `--personal` and `--global`:

```python
async def cmd_init(ctx: CommandContext, args: list[str]) -> None:
    force = "--force" in args or "-f" in args
    personal = "--personal" in args
    global_flag = "--global" in args
    
    # Mutually exclusive check
    if personal and global_flag:
        ctx.console.print("[error]--personal and --global are mutually exclusive[/error]")
        return
    
    if personal:
        await _init_personal(ctx, force)
    elif global_flag:
        await _init_global(ctx, force)
    else:
        await _init_team(ctx, force)  # Existing behavior
```

**New Functions:**

```python
async def _init_personal(ctx: CommandContext, force: bool) -> None:
    """Create .ite/AGENTS.md with user preferences."""
    # Path: ctx.config.cwd / ".ite" / "AGENTS.md"
    # Check exists + force
    # Prompt user for preferences
    # Generate via LLM with preference-focused prompt
    pass

async def _init_global(ctx: CommandContext, force: bool) -> None:
    """Create ~/.config/ite/AGENTS.md with global preferences."""
    # Path: get_data_dir() / "AGENTS.md"
    # Check exists + force
    # Prompt user for global preferences
    # Generate via LLM with global-focused prompt
    pass

async def _init_team(ctx: CommandContext, force: bool) -> None:
    """Existing team AGENTS.md creation (root level)."""
    pass
```

### Phase 3: Prompt Templates

**Team AGENTS.md Prompt (existing):**
```
Analyze the codebase and generate AGENTS.md with:
- Architecture overview
- Tech stack
- Build/test commands
- Code style patterns
- File organization
```

**Personal AGENTS.md Prompt:**
```
Ask the user: "What personal preferences would you like AI assistants to know for this project?"

Examples:
- Preferred coding style (functional vs OOP)
- Documentation preferences
- Testing approach preferences
- Naming conventions you prefer
- Things you want the AI to avoid

Generate AGENTS.md focused on personal conventions.
```

**Global AGENTS.md Prompt:**
```
Ask the user: "What are your global coding preferences that apply across all projects?"

Examples:
- Preferred languages/frameworks
- General coding philosophy
- Communication style preferences
- Review style preferences

Generate AGENTS.md with universal guidelines.
```

### Phase 4: Completion Card Updates

**Completion Card Text:**

| Tier | Path Display |
|------|--------------|
| Team | `AGENTS.md` (relative to cwd) |
| Personal | `.ite/AGENTS.md` |
| Global | `~/.config/ite/AGENTS.md` |

**Message:**
```
system  AGENTS.md Created
AGENTS.md has been created at {display_path}
{context if team tier: "Analyzed X root files, Y configs, Z samples"}
```

## Path Resolution Helpers

Add to `loader.py`:

```python
def get_personal_agents_path(cwd: Path) -> Path:
    """Path to personal AGENTS.md in .ite/ directory."""
    return cwd / WORKSPACE_DIR_NAME / AGENTS_MD_FILE

def get_global_agents_path() -> Path:
    """Path to global AGENTS.md in data directory."""
    return get_data_dir() / AGENTS_MD_FILE
```

## Backward Compatibility

- `/init` without flags continues to create team AGENTS.md
- `/init --force` continues to overwrite team AGENTS.md
- Existing loader behavior preserved for missing personal/global files
- All existing AGENTS.md files continue to work

## Testing Checklist

1. **Loader:**
   - [ ] Global AGENTS.md loads when present
   - [ ] Personal (.ite/) AGENTS.md loads when present
   - [ ] Team (root) AGENTS.md loads when present
   - [ ] Precedence: team > personal > global
   - [ ] Override files take precedence at each level

2. **Commands:**
   - [ ] `/init` creates team AGENTS.md
   - [ ] `/init --personal` creates personal AGENTS.md
   - [ ] `/init --global` creates global AGENTS.md
   - [ ] `--force` works with all tiers
   - [ ] Mutually exclusive flags validated

3. **Completion Cards:**
   - [ ] Shows correct relative path for each tier
   - [ ] Analysis details shown only for team tier

## Future Considerations

- UI to view/edit different tiers
- `/agents show --personal` to display personal preferences
- `/agents edit --global` to open global in editor
- Validation to warn when personal conflicts with team
