---
name: notebooklm
description: "Turn expert podcasts into personalized protocols with cited experiments. Load 300 episodes from terminal, run an expert-informed interview, build experiments in your Obsidian morning routine. Use when user says \"notebooklm\", \"load channel\", \"expert interview\", \"notebooklm ask\", \"health protocol\", or wants to turn expert content into actionable experiments."
---

# NotebookLM - Expert Knowledge to Action

Turn any expert's content into a personalized protocol with experiments you actually run. Load 300 YouTube episodes into NotebookLM from terminal, run a cited interview about your goal, create experiments in your Obsidian daily note.

## Prerequisites

### 1. Install nlm CLI

```bash
uv tool install notebooklm-mcp-cli
```

### 2. Install notebooklm-py

```bash
pip install "notebooklm-py[browser]"
playwright install chromium
```

### 3. Authenticate

```bash
nlm login
notebooklm login
```

Both open browser windows for Google OAuth. Complete login in browser, then return to terminal.

### 4. Obsidian Plugins

- **Dataview** (required) - for dashboard queries and experiment tracking

### 5. Vault Structure

Create this folder structure in your Obsidian vault:

```
Your Vault/
├── Notes/
│   ├── NotebookLM/           # All NotebookLM content
│   │   └── {notebook-slug}/  # e.g., huberman-health/
│   │       ├── Sources/      # Transcripts from videos
│   │       └── QA/           # Saved queries with citations
│   ├── Experiments/          # YOUR experiments from protocols
│   └── Daily/                # Daily notes
│       └── YYYY-MM-DD.md     # Morning routine check-ins
```

## Scripts

Located in `.Codex/skills/notebooklm/scripts/`:

| Script | Purpose |
|--------|---------|
| `load_channel.py` | Scrape YouTube channel + bulk-load videos into NotebookLM |
| `import_sources.py` | Create Obsidian source files with metadata and AI guides |
| `resolve_citations.py` | Convert `[N]` citations to `[[Source#^anchor]]` wikilinks |
| `backfill_fulltext.py` | Fetch full transcripts for source files |
| `extract_passages.py` | Extract cited passages from Q&A into source files |

## Full Workflow

### Phase 1: Load Expert Content

```bash
# 1. Scrape YouTube channel videos
python3 .Codex/skills/notebooklm/scripts/load_channel.py scrape \
  --channel "https://www.youtube.com/@hubermanlab" \
  --output /tmp/videos.json

# 2. Create notebook in NotebookLM
notebooklm create "Andrew Huberman - Health"
# Note the notebook ID from output

# 3. Load videos into NotebookLM
python3 .Codex/skills/notebooklm/scripts/load_channel.py load \
  --videos /tmp/videos.json \
  --notebook 24df7d35-... \
  --count 200 \
  --concurrency 20

# 4. Export sources list
nlm source list 24df7d35-... --json > /tmp/sources.json
```

### Phase 2: Import to Obsidian

```bash
# Run from your Obsidian vault root
cd ~/Documents/Obsidian

# Create source files with AI guides
python3 /path/to/.Codex/skills/notebooklm/scripts/import_sources.py \
  --sources /tmp/sources.json \
  --slug huberman-health \
  --dashboard "Huberman Health"

# Backfill full transcripts (takes a few minutes)
python3 /path/to/.Codex/skills/notebooklm/scripts/backfill_fulltext.py \
  --notebook 24df7d35-... \
  --slug huberman-health \
  --vault . \
  --concurrency 10
```

### Phase 3: Query with Citations

```bash
# Ask a question and save JSON output
nlm notebook query 24df7d35-... \
  "What does Huberman recommend for sleep optimization?" \
  --json > /tmp/qa-1.json

# Resolve citations to wikilinks in Obsidian
python3 /path/to/.Codex/skills/notebooklm/scripts/resolve_citations.py \
  --qa /tmp/qa-1.json \
  --sources /tmp/sources.json \
  --slug huberman-health \
  --vault . \
  --title "Sleep Optimization Protocol" \
  --notebook "Huberman Health" \
  --output "Notes/NotebookLM/huberman-health/QA/Sleep Optimization.md"
```

### Phase 4: Create Experiments

From the cited Q&A in Obsidian, you'll extract protocols into experiment files:

```markdown
---
type: experiment
date: 2026-04-20
protocol: "Morning Sunlight"
hypothesis: "10min sunlight before 10am improves sleep quality"
timeframe: "30 days"
---

# Morning Sunlight Protocol

## Protocol
1. Get 10+ minutes of outdoor light within 1hr of waking
2. Don't wear sunglasses (contacts/glasses OK)
3. Even if overcast, still effective

## Success Criteria
- [ ] Sleep latency < 15 minutes
- [ ] Wake time consistency ±30min
- [ ] Subjective energy 7+/10 by 10am

## Log
| Date | Done | Notes |
|------|------|-------|
| 2026-04-20 | ✓ | Felt alert by 9:30am |
```

## Vault Structure After Setup

```
Your Vault/
├── Notes/
│   ├── NotebookLM/
│   │   ├── Huberman Health.md          # Main notebook index (type: notebook)
│   │   └── huberman-health/
│   │       ├── Sources/
│   │       │   ├── The Science of Sleep.md     # Video transcript
│   │       │   ├── Light Exposure.md
│   │       │   └── ...
│   │       └── QA/
│   │           ├── Sleep Optimization.md         # Cited answers
│   │           └── Cold Exposure Research.md
│   ├── Experiments/
│   │   ├── Morning Sunlight Protocol.md
│   │   ├── Cold Shower Protocol.md
│   │   └── ...
│   └── Dashboards/
│       └── Health.md                   # Dataview query: active experiments
└── Notes/Daily/
    └── 2026-04-20.md                   # Morning routine asks about experiments
```

## Daily Morning Routine Note

Your daily note template includes:

```markdown
## Morning Experiments

```dataview
TABLE hypothesis, timeframe
FROM "Notes/Experiments"
WHERE timeframe
```

### Check-ins
- [ ] Morning sunlight: ___ (duration)
- [ ] How did yesterday's experiments go?
- [ ] Any observations to note?
```

## Limitations

- **300 sources per notebook max** - Create multiple notebooks for larger channels
- **Videos may fail** if private/deleted/region-locked (check `/tmp/channel-load-errors.json`)
- **Processing time** - NotebookLM indexes videos server-side after upload (minutes)
- **Transcript fetching** - Requires `backfill_fulltext.py` to populate source files

## Quick Reference

```bash
# List notebooks
nlm notebook list
notebooklm list

# Create notebook
notebooklm create "Expert Name - Topic"

# Query
nlm notebook query <notebook-id> "Your question" --json

# List sources
nlm source list <notebook-id> --json > /tmp/sources.json
```

## Source File Format

Each source file has frontmatter for Dataview queries:

```yaml
---
type: notebook-source
source_id: "uuid..."
notebook_id: "uuid..."
url: "https://www.youtube.com/watch?v=..."
source_type: youtube
status: active
date: 2026-04-15
topics:
  - "[[sleep]]"
  - "[[circadian rhythm]]"
related:
  - "[[Notes/Dashboards/Health]]"
---
```
