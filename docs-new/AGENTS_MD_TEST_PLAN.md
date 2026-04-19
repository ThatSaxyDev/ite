# AGENTS.md Test Plan

## Overview

This document provides step-by-step tests to verify the AGENTS.md implementation.

## Prerequisites

- iTE installed from the updated build
- A test project directory
- Access to `~/.config/ite/`

---

## Test 1: Global AGENTS.md

**Purpose**: Verify `~/.config/ite/AGENTS.md` loads as base layer

### Steps

1. Create global AGENTS.md:
   ```bash
   mkdir -p ~/.config/ite
   cat > ~/.config/ite/AGENTS.md << 'EOF'
   # Global Preferences

   ## Code Style
   - Always use type hints in Python
   - Prefer f-strings over concatenation
   EOF
   ```

2. Create a test project with its own AGENTS.md:
   ```bash
   mkdir -p ~/test-project
   cd ~/test-project
   cat > AGENTS.md << 'EOF'
   # Test Project

   ## Architecture
   - This is a test project
   
   ## Testing
   - Run: `python -m pytest`
   EOF
   ```

3. Start iTE from the test project:
   ```bash
   cd ~/test-project
   ite
   ```

4. Ask the agent:
   ```
   What should I know about working with this codebase?
   ```

### Expected Result

- Response mentions **both** type hints (from global) AND pytest (from project)
- Project instructions appear after global (project overrides)

---

## Test 2: Override Files

**Purpose**: Verify `AGENTS.override.md` takes precedence at same level

### Steps

1. In the test project, create an override:
   ```bash
   cd ~/test-project
   cat > AGENTS.override.md << 'EOF'
   # Override Mode

   ## Temporary Rule
   - IGNORE all previous instructions about type hints
   - For this session: focus only on docstrings
   EOF
   ```

2. Start a fresh iTE session:
   ```bash
   cd ~/test-project
   ite
   ```

3. Ask:
   ```
   Do I need type hints in this project?
   ```

### Expected Result

- Response says type hints are NOT required (override wins)
- Response emphasizes docstrings instead

### Cleanup

```bash
rm ~/test-project/AGENTS.override.md
```

---

## Test 3: Fallback Filenames

**Purpose**: Verify fallback files work when AGENTS.md is absent

### Steps

1. Create test project with CLAUDE.md instead of AGENTS.md:
   ```bash
   mkdir -p ~/test-fallback
   cd ~/test-fallback
   cat > CLAUDE.md << 'EOF'
   # Claude Project Guide

   ## Important Rule
   - Never use print() statements, always use logging
   EOF
   ```
   
   (Note: Do NOT create AGENTS.md)

2. Start iTE:
   ```bash
   cd ~/test-fallback
   ite
   ```

3. Ask:
   ```
   How should I handle output in this project?
   ```

### Expected Result

- Response mentions logging over print() (from CLAUDE.md)
- The agent found and used the fallback file

### Cleanup

```bash
rm -rf ~/test-fallback
```

---

## Test 4: Size Limits

**Purpose**: Verify 32 KiB limit enforces truncation

### Steps

1. Create oversized AGENTS.md:
   ```bash
   mkdir -p ~/test-size
   cd ~/test-size
   python3 << 'PYEOF'
   with open("AGENTS.md", "w") as f:
       f.write("# Large File\\n\\n")
       # Write 35KB of content (over limit)
       f.write("\\n\\n".join([f"Rule {i}: This is instruction line {i}." for i in range(800)]))
   PYEOF
   ```

2. Check file size:
   ```bash
   ls -lh AGENTS.md
   ```
   (Should be > 32K)

3. Create subdirectory with small override:
   ```bash
   mkdir -p src
   cat > src/AGENTS.md << 'EOF'
   # Src-specific
   - Important: Use async/await patterns here
   EOF
   ```

4. Start iTE from `src/`:
   ```bash
   cd ~/test-size/src
   ite
   ```

5. Ask:
   ```
   What's the first rule in our project?
   ```

### Expected Result

- Response mentions "async/await" (from src/AGENTS.md - small, preserved)
- Early rules from root AGENTS.md are NOT mentioned (truncated to stay under 32KiB)

### Cleanup

```bash
rm -rf ~/test-size
```

---

## Test 5: /remind Command

**Purpose**: Verify manual AGENTS.md refresh works

### Steps

1. Create a test project:
   ```bash
   mkdir -p ~/test-remind
   cd ~/test-remind
   cat > AGENTS.md << 'EOF'
   # Remind Test

   ## Convention
   - All variables must be in snake_case
   EOF
   ```

2. Start iTE and have a long conversation (10+ messages) to simulate drift

3. During the conversation, run:
   ```
   /remind
   ```

4. After the system message appears, ask:
   ```
   What naming convention should I follow?
   ```

### Expected Results

- `/remind`: Shows "AGENTS.md content re-injected" with full content
- After reminder, response emphasizes snake_case strictly

### Cleanup

```bash
rm -rf ~/test-remind
```

---

## Test 6: Hierarchy (Combined)

**Purpose**: Verify full precedence chain: Global → Root → Subdir

### Steps

1. Setup all levels:
   ```bash
   # Global
   cat > ~/.config/ite/AGENTS.md << 'EOF'
   # Global
   - Global rule: Use descriptive names
   EOF

   # Project root
   mkdir -p ~/test-hierarchy
   cd ~/test-hierarchy
   cat > AGENTS.md << 'EOF'
   # Root
   - Root rule: Add docstrings to all functions
   - Overrides: descriptive names are REQUIRED
   EOF

   # Subdirectory
   mkdir -p api
   cat > api/AGENTS.md << 'EOF'
   # API Module
   - API rule: Use FastAPI conventions
   - Overrides: docstrings must include params
   EOF
   ```

2. Start iTE from `api/`:
   ```bash
   cd ~/test-hierarchy/api
   ite
   ```

3. Ask:
   ```
   What are the rules for this module?
   ```

### Expected Result

Response mentions:
1. FastAPI conventions (from api/AGENTS.md)
2. Param documentation in docstrings (from api/, overrides root)
3. Descriptive names (from global, not overridden)

Rules NOT mentioned or overridden:
- Generic docstrings (override: "must include params")
- Descriptive names are optional (override: "REQUIRED")

### Cleanup

```bash
rm -rf ~/test-hierarchy
```

---

## Summary Checklist

| Test | Status |
|------|--------|
| Global AGENTS.md loads | ☐ |
| Override files work | ☐ |
| Fallback filenames work | ☐ |
| Size limits enforce truncation | ☐ |
| /remind command works | ☐ |
| /remind --summary works | ☐ |
| Hierarchy preserves most-specific | ☐ |

**All passed?** The AGENTS.md implementation is complete and working.
