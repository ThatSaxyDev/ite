# BRIEF: The Haunted Code Review Agent

## A 50-Year Specification for Building a Local Code Review Engine That Remembers Everything

---

### Table of Contents

1. [Vision & Philosophy](#vision--philosophy)
2. [Name Origin](#name-origin)
3. [Core Insight](#core-insight)
4. [Architecture Overview](#architecture-overview)
5. [Data Model: The Ledger](#data-model-the-ledger)
6. [The Five-Layer Code Review System](#the-five-layer-code-review-system)
7. [Tool Specification](#tool-specification)
8. [Memory Architecture](#memory-architecture)
9. [Extraction Policy](#extraction-policy)
10. [Query Scope Control](#query-scope-control)
11. [Performance Targets](#performance-targets)
12. [Deduplication Strategy](#deduplication-strategy)
13. [Search Logic](#search-logic)
14. [Persona & Voice](#persona--voice)
15. [Storage Layer](#storage-layer)
16. [Configuration](#configuration)
17. [Implementation Order](#implementation-order)
18. [Extensibility Points](#extensibility-points)
19. [Anti-Patterns to Avoid](#anti-patterns-to-avoid)
20. [Testing Strategy](#testing-strategy)

---

## Vision & Philosophy

### The "Slightly Haunted Senior Engineer"

Build an agent that acts as a slightly-haunted senior engineer who:

- **Never forgets**: Every decision, every promise, every mistake is recorded
- **Speaks plainly**: Warnings have personality and teeth
- **Knows your codebase**: Remembers why things were built that way
- **Protects Future You**: Catches patterns that lead to past incidents

> "I won't block this merge. But I won't forget you saw this."  
> vs.  
> "3 potential issues found"

This is not another linter. This is institutional memory made alive.

---

## Name Origin

**BRIEF** — **B**ased **R**epository of **I**mportant **E**vents and **F**acts

*"Based means what I say it means. It's based."*

---

## Core Insight

### The 80% Problem

Most architectural decisions are never formally documented. They exist only in:

- Commit messages (sometimes)
- Code comments (rarely)
- Issue bodies (if you're lucky)
- CODE ITSELF

BRIEF captures decisions from **code AND comments**, not just formal ADR documents. It treats git history as the primary source of truth for "why this exists."

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          BRIEF                                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Git Integration │ │ GitHub/GitLab │ │ Local Memory Store  │  │
│  │    Layer      │  │    API      │  │    (The Ledger)     │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              The Five-Layer Review Engine                │  │
│  │  Layer 1: Memory Conflicts    │ Semantic similarity      │  │
│  │  Layer 2: Promise Verification│ "You promised X, Y has  │  │
│  │  Layer 3: Security Sentinel  │ Past decisions + patterns │  │
│  │  Layer 4: Code Intelligence │ New deps, tech drift     │  │
│  │  Layer 5: Pattern Enforcement│ Reviewer rules captured  │  │
│  └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Tools (Slash Commands)                │  │
│  │  /brief ask  /brief pre-mortem  /brief promises           │  │
│  │  /brief decisions  /brief incidents  /brief rules         │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Model: The Ledger

### Core Entities

All entities live in `~/.ite/brief/` directory.

#### 1. Decision

```json
{
  "id": "uuid-v4",
  "type": "decision",
  "title": "Chose PostgreSQL over MongoDB for user data",
  "summary": "PostgreSQL's relational nature better suits our user-permission model. ACID compliance critical for billing.",
  "context": {
    "files": ["src/db/models.go", "src/auth/permissions.go"],
    "commits": ["abc123", "def456"],
    "issue_refs": ["#42"]
  },
  "participants": ["alice", "bob"],
  "timestamp": "2024-03-15T10:30:00Z",
  "expires": null,
  "status": "active"
}
```

#### 2. Promise

```json
{
  "id": "uuid-v4",
  "type": "promise",
  "title": "Session TTL will be 30 seconds",
  "description": "For security, sessions expire after 30 seconds of inactivity",
  "source": {
    "type": "issue",
    "id": "#128",
    "body": "Session TTL should be 30s not 30min - security risk otherwise"
  },
  "verification": {
    "pattern": "session.*ttl.*30",
    "files": ["src/auth/session.go"],
    "expected": "ttl_seconds = 30",
    "comparator": "equals"
  },
  "status": "fulfilled",
  "created_at": "2024-04-01T09:00:00Z",
  "fulfilled_at": "2024-04-02T14:20:00Z"
}
```

#### 3. Rule

```json
{
  "id": "uuid-v4",
  "type": "rule",
  "title": "No new JS frameworks without team approval",
  "description": "We have too much tech fragmentation. New frameworks require RFC.",
  "rationale": "We've accumulated 4 state management solutions. Consolidation needed.",
  "pattern": {
    "type": "dependency",
    "match": "new:package.json",
    "exclude": ["react", "vue", "angular", "svelte"]
  },
  "enforcement": "warn",
  "created_by": "brief",
  "created_at": "2024-05-10T11:00:00Z"
}
```

#### 4. Incident

```json
{
  "id": "uuid-v4",
  "type": "incident",
  "title": "Production outage: Cache invalidation bug",
  "description": "Redis keys not invalidated on user role change. Admin permissions persisted for wrong users.",
  "root_cause": "Cache TTL was 1 hour. Role changes not in cache key.",
  "files_affected": ["src/cache/redis.go"],
  "commits_associated": ["fix-cache-invalidation"],
  "tags": ["cache", "security", "redis"],
  "resolved": true,
  "occurred_at": "2024-02-20T03:00:00Z",
  "resolved_at": "2024-02-20T08:00:00Z"
}
```

#### 5. Pattern

```json
{
  "id": "uuid-v4",
  "type": "pattern",
  "title": "Database migration pattern",
  "description": "We use numbered migrations in alembic/versions/",
  "example_files": ["alembic/versions/001_user_schema.py"],
  "enforced": true,
  "created_at": "2024-01-15T10:00:00Z"
}
```

---

## The Five-Layer Code Review System

### Layer 1: Memory Conflicts

**Purpose**: Detect when new code contradicts past decisions.

**Mechanism**:
1. Embed code changes as semantic vectors (using LLM or sentence transformers)
2. Query the Decision store for similar semantics (cosine similarity > 0.85)
3. If conflict found, surface with context

**Example**:
```
⚠️  MEMORY CONFLICT DETECTED

You changed session TTL to 300 seconds (5 minutes).

Past decision (2024-03-15):
  "Session TTL will be 30 seconds"
  Issue #128: "Session TTL should be 30s not 30min - security risk"
  
This contradicts the active promise. Did you mean to override this decision?
```

### Layer 2: Promise Verification

**Purpose**: Verify code fulfills explicit commitments in issues/PRs.

**Mechanism**:
1. After PR merge, extract "promises" from issue body/PR description
2. Store promises in Ledger with verification rules
3. On subsequent changes, check if files mentioned in promise are modified
4. Compare new code against promise's expected value

**Verification Types**:
- `equals`: Exact value match
- `contains`: String/substring match  
- `pattern`: Regex match
- `not_contains`: Should NOT contain pattern
- `function`: Custom Python function (sandboxed)

### Layer 3: Security Sentinel

**Purpose**: Learn from past security incidents.

**Mechanism**:
1. Maintain library of past Incident with security tags
2. Scan new code for similar patterns
3. Check against known vulnerable patterns (OWASP, CWE)
4. Warn if code resembles past security bugs

**Incident Tag Mapping**:
```
security::sql_injection   → check for raw SQL with user input
security::xss             → check for innerHTML, dangerouslySetInnerHTML
security::crets           → check for hardcoded API keys, tokens
security::auth            → check for authorization bypass patterns
```

### Layer 4: Code Intelligence

**Purpose**: Detect tech drift and new dependencies.

**Mechanism**:
1. Maintain baseline of current dependencies, patterns, file structure
2. Scan new code for:
   - New npm/pip packages added
   - New file patterns (new directories, new file types)
   - Framework upgrades
   - API usage changes

**Example**:
```
📦 NEW DEPENDENCY DETECTED

Added: date-fns (npm)
Files: src/utils/date.ts

Current project has 7 date libraries:
  - moment (deprecated)
  - dayjs
  - luxon
  - native Date
  - chrono-node
  - nunjucks-date-filter
  - date-fns (NEW)

Consider consolidation.
```

### Layer 5: Pattern Enforcement

**Purpose**: Enforce patterns defined by human reviewers.

**Mechanism**:
1. Reviewers can create rules from PR feedback
2. Rules stored in Ledger with pattern matchers
3. On future PRs, auto-enforce rules
4. Can be "warn" (non-blocking) or "block" (requires override)

**Example Rule Creation**:
```markdown
In PR #234, reviewer wrote:
> "Don't use async/await in loops, use Promise.all instead"

BRIEF extracts this as:
  Rule: "No async/await in loops"
  Pattern: "for.*\\{.*await"
  Enforcement: warn
```

---

## Tool Specification

### Core Tools (New Built-ins)

#### 1. brief_fetch_issues

Fetch issues from GitHub API or read from local markdown files.

```
Tool: brief_fetch_issues
Input: 
  - source: "github" | "local"
  - owner: string (GitHub owner)
  - repo: string (GitHub repo)
  - state: "open" | "closed" | "all"
  - labels: string[]
  - local_path: string (for local source)
Output:
  - list of issues with: id, title, body, state, labels, created_at, closed_at
```

#### 2. brief_index_commits

Process git history to extract semantic information from commits.

```
Tool: brief_index_commits
Input:
  - since: date (optional)
  - max_count: int (default 1000)
  - extract_decisions: bool (default true)
Output:
  - indexed: int
  - decisions_found: int
  - errors: string[]
```

#### 3. brief_decision_extract

After every PR merge, automatically extract decisions from:
- Commit messages
- PR description
- Changed code
- Comments in code

```
Tool: brief_decision_extract
Input:
  - pr_url: string (or last merged PR)
  - scan_code: bool (default true)
Output:
  - decisions: Decision[]
  - promises: Promise[]
  - patterns: Pattern[]
```

#### 4. brief_promise_check

Verify if code changes fulfill promises from issues.

```
Tool: brief_promise_check
Input:
  - files: string[]
Output:
  - fulfilled: Promise[]
  - broken: Promise[]
  - new_candidates: Promise[]
```

#### 5. brief_onboarding

Generate "briefing for new developer" from Ledger.

```
Tool: brief_onboarding
Input:
  - developer_name: string
  - focus_areas: string[] (optional)
Output:
  - briefing: markdown string
  - key_decisions: Decision[]
  - active_rules: Rule[]
  - past_incidents: Incident[]
```

#### 6. brief_pre_mortem

Before starting work on a feature, search history for related failures.

```
Tool: brief_pre_mortem
Input:
  - feature_description: string
  - files_affected: string[]
Output:
  - related_incidents: Incident[]
  - similar_decisions: Decision[]
  - warnings: string[]
```

#### 7. brief_ask

Conversational search through the Ledger.

```
Tool: brief_ask
Input:
  - question: string
Output:
  - answers: { text: string, source: LedgerRef, confidence: float }[]
  - related_decisions: Decision[]
```

### Slash Commands

| Command | Action |
|---------|--------|
| `/brief ask <question>` | Search the Ledger conversationally |
| `/brief pre-mortem <feature>` | Run pre-mortem analysis |
| `/brief promises` | List active promises and their status |
| `/brief decisions` | Show recent decisions |
| `/brief incidents` | Show relevant past incidents |
| `/brief rules` | List enforced patterns |
| `/brief onboarding` | Generate developer briefing |
| `/brief extract` | Manually trigger decision extraction |
| `/brief init` | Initialize Ledger for a new repo |

---

## Memory Architecture

### Storage Locations

```
~/.ite/brief/                          # Global BRIEF store
├── config.json                       # BRIEF configuration
├── decisions/                        # Decision records
│   └── {year}/{month}/{uuid}.json   # Organized by month
├── promises/                         # Promise records
│   └── {status}/{uuid}.json          # pending/fulfilled/broken
├── rules/                           # Enforced patterns
│   └── {uuid}.json
├── incidents/                        # Past failures
│   └── {year}/{uuid}.json
├── patterns/                        # Code patterns
│   └── {uuid}.json
├── embeddings/                      # Vector embeddings (optional)
│   └── {year}/{quarter}.bin
└── .index                           # Search index
```

### Embedding Strategy

For semantic search, use one of:

1. **LLM-based** (simplest): Use the configured LLM to embed query and results
2. **Local embeddings**: Sentence-transformers (`all-MiniLM-L6-v2`)
3. **Keyword fallback**: If semantic search unavailable, use BM25

### Index Schema

```json
// .index file
{
  "version": 1,
  "last_indexed": "2024-05-15T10:00:00Z",
  "total_decisions": 142,
  "total_promises": 89,
  "total_incidents": 23,
  "commit_index": {
    "abc123": "decision-uuid-1",
    "def456": "decision-uuid-2"
  }
}
```

---

## Extraction Policy

### The "Not Everything" Principle

Not every commit creates a BRIEF entity. ~90% of commits are likely noise (typos, whitespace fixes, trivial changes). BRIEF extracts **meaningful** entities only.

### What Gets Stored by Source Type

| Source | Extraction Criteria | Expected Volume |
|--------|---------------------|-----------------|
| **Commits** | Message contains architectural keywords: "chose", "migrated", "moved to", "replaced", "decision", "architecture", "选择" | 100-500 per repo lifetime |
| **Issues** | Body contains "will", "should", "must", "promise", "we need to", "technical debt" | 50-200 per repo |
| **PR Descriptions** | Contains "rationale", "why", "because", "decision" | 50-200 per repo |
| **Code Reviews** | Reviewer patterns: "don't do X", "always use Y", "we should" | 20-100 per repo |
| **Incidents** | Tagged issues with "outage", "bug", "incident", "failure", "hotfix" | 10-50 per repo |
| **Random commits** | "fix typo", "update", "wip" | Ignored (no entity created) |

### Decision to Extract

The extraction engine uses the LLM to classify:

1. **Is this commit/issue/PR describing a decision?**
2. **If yes, what category?** (decision, promise, rule, pattern, incident)
3. **Is the context non-trivial?** (skip 1-liners that say "fix" or "update")

If all answers are "yes" → create entity. Otherwise → skip.

### Example Extraction Flow

```
Commit: "Chose PostgreSQL over MongoDB for user data. 
        Relational model better fits permissions. ACID for billing."

Classification:
  - Decision: YES
  - Category: decision
  - Files affected: src/db/models.go, src/auth/permissions.go
  - Participants: git author (mapped to team member)
  
Entity created: Decision{title: "Chose PostgreSQL over MongoDB", ...}
```

```
Commit: "fix typo in comment"

Classification:
  - Decision: NO
  
Result: No entity created. Not stored.
```

---

## Query Scope Control

### Search, Not Dump

When you ask BRIEF, it doesn't scan "everything." It searches for **relevant matches** only. Context bloat is avoided by design.

### How Queries Work

```
You ask: "Why do we use PostgreSQL?"

1. BRIEF converts question to embedding vector
2. Searches Decision store for similarity > 0.85
3. Returns top 3-5 most relevant entities (not all matches)
4. Loads only those entities into context (~500 words)
5. Passes to LLM for answer generation

Result: ~500 words of relevant context, not 100,000.
```

### Per-Command Context Limits

| Command | Context Scope | Typical Tokens |
|---------|--------------|----------------|
| `/brief ask <question>` | Top 3-5 relevant entities | ~500-800 |
| `/brief pre-mortem` | Related incidents + similar decisions | ~600-1000 |
| `/brief review --staged` | Layer outputs only | ~400-600 |
| `/brief decisions` | Last 10 decisions (summarized) | ~300-500 |
| `/brief onboarding` | Summarized summary of everything | ~1500-2000 |
| `/brief promises` | Active promises + verification status | ~400-600 |

### Context Compression

When a query needs multiple entities, BRIEF can summarize them before sending to LLM:

```
Original: 3 decisions × 200 words = 600 words
Compressed: "In March and May 2024, team decided to use PostgreSQL 
             for user data due to ACID compliance. Avoided MongoDB
             for the same reason. Related decisions."
             
Result: ~80 words (92% reduction)
```

This keeps LLM context lean while preserving meaning.

---

## Performance Targets

### Storage Scale

A mature repo using BRIEF actively:

| Entity Type | Expected Count |
|-------------|----------------|
| Decisions | 100-500 |
| Promises (active) | 20-50 |
| Promises (fulfilled) | 50-150 |
| Rules | 20-50 |
| Incidents | 10-30 |
| Patterns | 10-30 |
| **Total** | **~300-1000 entities |

Not millions. Hundreds.

### Query Performance

| Operation | Target |
|------------|--------|
| Semantic search (top 5) | < 500ms |
| Full repo index (10,000 commits) | < 5 minutes |
| Pre-mortem analysis | < 2 seconds |
| Onboarding generation | < 5 seconds |
| Layer 5 review (50-file PR) | < 30 seconds |

### Context Budgets

| Scenario | Max Context |
|----------|-------------|
| Simple ask | 1,000 tokens |
| Pre-mortem | 2,000 tokens |
| Full review | 3,000 tokens |
| Onboarding | 4,000 tokens |

---

## Deduplication Strategy

### The Memory Bloat Problem

If BRIEF indexes every similar commit, the Ledger grows unmanageably. Need to prevent this.

### Deduplication Approaches

**1. Semantic Deduplication**
- When extracting a new decision, search for similar existing ones (similarity > 0.90)
- If found, optionally merge or link rather than create duplicate

**2. Commit-Level Deduplication**
- Maintain a commit SHA index (already in `.index`)
- If commit already indexed → skip

**3. Temporal Deduplication**
- Related decisions within 7 days of each other → suggest merge
- Example: Multiple commits all about "choosing auth framework"

**4. Auto-Archiving**
- Decisions older than 2 years → move to "archive" (still queryable but not in main index)
- Incidents resolved > 1 year ago → reduced priority in search

### What Doesn't Get Deduplicated

- Promises: Each issue/promise is unique
- Rules: Each rule may have different patterns
- Incidents: Each incident is a distinct historical record

---

## Search Logic

### The Three-Tier Search System

**Tier 1: Semantic Search (Primary)**
- Embed query → vector search → top-K entities by similarity
- Threshold: 0.85 (configurable)
- Returns: scored results with confidence

**Tier 2: Keyword Fallback**
- If embedding provider unavailable → BM25 keyword search
- Weaker semantic understanding but no embedding dependency

**Tier 3: Exact Match**
- For structured queries like `/brief decisions --id <uuid>`
- Direct lookup, no search needed

### Search Flow Diagram

```
Query: "Why do we use PostgreSQL?"
         │
         ▼
    [Convert to embedding]
         │
         ▼
    [Tier 1: Semantic Search] ──→ Similarity > 0.85?
         │                              │
         │                         YES ▼
         │                     [Return top 5]
         │                              │
         ▼                              ▼
    [Tier 2: BM25] ─────────────────────┘
         │
         ▼
    [Tier 3: Exact Match (if ID provided)]
         │
         ▼
    [Return results to LLM]
```

### Confidence Scoring

Every search result includes a confidence score:

```json
{
  "answers": [
    {
      "text": "PostgreSQL was chosen for ACID compliance...",
      "source": {"type": "decision", "id": "uuid-42"},
      "confidence": 0.92
    },
    {
      "text": "Related: team avoided MongoDB due to...",
      "source": {"type": "decision", "id": "uuid-89"},
      "confidence": 0.78
    }
  ]
}
```

Results below `min_conflict_score` (default 0.85) can be filtered out.

---

## Persona & Voice

### The Haunted Senior Engineer

BRIEF speaks with a specific personality:

**Tone**: 
- Direct, slightly wry
- Never aggressive, but persistent
- Uses "we" when appropriate
- Remembers everything

**Example Messages**:

| Situation | Message |
|-----------|---------|
| Conflict with past decision | "Hey, we decided something different back in March. Want me to drag up the context?" |
| Broken promise | "This says 300 seconds. You promised 30 seconds in #128. Did that promise become... flexible?" |
| New dependency | "Adding date-fns? We're up to 8 date libraries now. Someone should write a history of our relationship with time." |
| Security warning | "This feels like the cache bug from February. Want me to pull up what happened?" |
| Blocking rule violation | "Rule says no new frameworks without RFC. This one's going to need an override from someone who can say yes." |

### Voice Configuration

Allow customization via config:

```toml
[brief]
persona = "haunted"  # haunted, mentor, blunt, pirate
severity = "medium"  # strict, medium, gentle
```

---

## Configuration

### Config File: `~/.ite/brief/config.json`

```json
{
  "version": 1,
  "providers": {
    "github": {
      "enabled": true,
      "token_env": "GITHUB_TOKEN",
      "default_repos": ["my-org/*"]
    },
    "gitlab": {
      "enabled": false,
      "url": "https://gitlab.com",
      "token_env": "GITLAB_TOKEN"
    },
    "local": {
      "enabled": true,
      "path": "docs/decisions"
    }
  },
  "embedding": {
    "provider": "llm",  // or "sentence-transformers"
    "model": null,     // uses configured model
    "dimension": 1536
  },
  "review": {
    "layers_enabled": [1, 2, 3, 4, 5],
    "auto_extract": true,
    "block_on_broken_promise": false,
    "min_conflict_score": 0.85
  },
  "persona": {
    "style": "haunted",
    "severity": "medium",
    "include_history": true
  },
  "storage": {
    "path": "~/.ite/brief",
    "max_embedding_cache_mb": 500
  }
}
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | GitHub API token for issue fetching |
| `GITLAB_TOKEN` | GitLab API token |
| `ITE_BRIEF_DISABLED` | Set to "1" to disable BRIEF |

---

## Implementation Order

### Phase 1: Foundation (Weeks 1-2)

1. **Create Storage Layer**
   - Implement `~/.ite/brief/` directory structure
   - JSON file read/write for entities
   - Basic index management

2. **Git Integration**
   - Enhance existing `git_tools.py`:
     - `git_log_with_bodies`: Full commit details
     - `git_diff_semantic`: Understand what changed semantically
   - Create `brief/git.py` module

3. **Basic Tools**
   - `brief_decision_extract`: Extract decisions from commits
   - `brief_index_commits`: Batch process git history
   - Storage: `brief/storage.py`

**Deliverable**: Can index a repo's git history and display past decisions.

### Phase 2: Issue Integration (Week 3)

4. **GitHub/GitLab Integration**
   - Create `brief/github.py`: Fetch issues via API
   - Create `brief/gitlab.py`: Fetch issues from self-hosted GitLab
   - Local fallback: Parse markdown files in `docs/decisions/`

5. **Promise Extraction**
   - Parse issue bodies for "will", "should", "must", "promise"
   - Store as Promise entities with verification rules
   - `brief_promise_check`: Verify against current code

**Deliverable**: Can fetch issues and track if code fulfills promises.

### Phase 3: The Review Engine (Weeks 4-5)

6. **Five-Layer Implementation**
   - Layer 1: Semantic conflict detection
   - Layer 2: Promise verification
   - Layer 3: Security sentinel with incident library
   - Layer 4: Dependency tracking
   - Layer 5: Pattern extraction from PR comments

7. **Integration Hooks**
   - `brief_review_pre_push`: Run before `git push`
   - `brief_review_pr`: Run as GitHub PR comment
   - Command: `git brief review`

**Deliverable**: Full five-layer review on demand.

### Phase 4: Polish & Launch (Week 6)

8. **Slash Commands**
   - `/brief ask <question>`
   - `/brief pre-mortem <feature>`
   - `/brief onboarding`
   - `/brief extract`
   - `/brief init`

9. **Persona Tuning**
   - Implement voice system
   - Add customization options
   - Write personality prompts

10. **Documentation**
    - User guide
    - Config reference
    - Troubleshooting

**Deliverable**: Shippable local tool.

---

## Extensibility Points

### Custom Storage Backends

```python
# brief/storage/backends.py
class StorageBackend(Protocol):
    async def save(self, entity: BriefEntity) -> None: ...
    async def get(self, id: str) -> BriefEntity | None: ...
    async def query(self, filter: QueryFilter) -> list[BriefEntity]: ...
    async def search(self, embedding: list[float], top_k: int) -> list[BriefEntity]: ...

# Implementations:
class JsonFileBackend(StorageBackend): ...
class SqliteBackend(StorageBackend): ...
class PostgresBackend(StorageBackend): ...
class ChromaDBBackend(StorageBackend): ...  # for embeddings
```

### Custom Embedding Providers

```python
# brief/embeddings/providers.py
class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class LLMEmbeddingProvider(EmbeddingProvider): ...
class SentenceTransformerProvider(EmbeddingProvider): ...
class OllamaEmbeddingProvider(EmbeddingProvider): ...
```

### Custom Source Integrations

```python
# brief/sources/__init__.py
class IssueSource(Protocol):
    async def fetch_issues(self, repo: str, **opts) -> list[Issue]: ...
    async def fetch_issue(self, repo: str, id: str) -> Issue | None: ...

class GitHubSource(IssueSource): ...
class GitLabSource(IssueSource): ...
class LocalMarkdownSource(IssueSource): ...
class JiraSource(IssueSource): ...
```

---

## Anti-Patterns to Avoid

### 1. False Positives Kill Trust

If BRIEF warns constantly about irrelevant things, users will ignore it.

**Mitigation**:
- Set similarity threshold high (0.85+, not 0.5)
- Allow explicit user dismissal with feedback
- Track false positive rate

### 2. Memory Bloat

Indexing every commit will make the system unusable.

**Mitigation**:
- Only index commits with meaningful messages
- Deduplicate similar decisions
- Archive old decisions after 2 years (but keep accessible)

### 3. Privacy Leakage

Don't index sensitive info in commits.

**Mitigation**:
- Scrub secrets from consideration
- Don't embed API keys, tokens, credentials
- Allow repo-specific privacy rules

### 4. Blocking Fatigue

Blocking too much kills velocity.

**Mitigation**:
- Default to warnings, not blocks
- Allow override with rationale
- Track "blocked" count, alert if too high

---

## Testing Strategy

### Unit Tests

| Component | Tests |
|-----------|-------|
| Storage | CRUD for each entity type, indexing, search |
| Extraction | Commit message parsing, decision type classification |
| Verification | Promise matching, pattern detection |
| Embedding | Vector similarity, quantization |

### Integration Tests

| Test | Description |
|------|-------------|
| Full repo index | Index real repo, verify entities created |
| Promise cycle | Create promise → write code → check fulfillment |
| Conflict detection | Write conflicting code → verify warning |
| GitHub integration | Fetch real issues (mock or test org) |

### Persona Tests

| Test | Scenario | Expected |
|------|----------|----------|
| Conflict message | Code contradicts decision | Wry warning with context |
| Broken promise | Code doesn't match issue | Direct "you promised X" |
| Security warning | Code resembles past bug | Cautious "this feels like..." |

### Performance Tests

- Index 10,000 commits → < 5 minutes
- Semantic search → < 500ms
- Full review on 50-file PR → < 30 seconds

---

## File Structure (Implementation Reference)

```
src/ite/
├── brief/                             # NEW: BRIEF module
│   ├── __init__.py
│   ├── config.py                      # Config loading
│   ├── storage/                       # Storage layer
│   │   ├── __init__.py
│   │   ├── base.py                    # StorageBackend protocol
│   │   ├── json_store.py              # JSON file implementation
│   │   └── index.py                   # Search index
│   ├── entities/                      # Data models
│   │   ├── __init__.py
│   │   ├── decision.py
│   │   ├── promise.py
│   │   ├── rule.py
│   │   ├── incident.py
│   │   └── pattern.py
│   ├── extraction/                   # Decision extraction
│   │   ├── __init__.py
│   │   ├── commit_parser.py
│   │   ├── issue_parser.py
│   │   └── code_analyzer.py
│   ├── review/                        # Five-layer review
│   │   ├── __init__.py
│   │   ├── layer1_conflicts.py
│   │   ├── layer2_promises.py
│   │   ├── layer3_security.py
│   │   ├── layer4_intelligence.py
│   │   └── layer5_patterns.py
│   ├── sources/                       # Issue sources
│   │   ├── __init__.py
│   │   ├── github.py
│   │   ├── gitlab.py
│   │   └── local.py
│   ├── embeddings/                    # Semantic search
│   │   ├── __init__.py
│   │   └── providers.py
│   └── cli.py                         # Slash commands
├── tools/
│   ├── builtin/
│   │   ├── brief_tools.py             # NEW: Main BRIEF tools
│   │   └── git_tools.py               # ENHANCED: More git commands
│   └── mcp/
│       └── brief_mcp.py               # OPTIONAL: MCP server for BRIEF
└── commands/
    ├── brief.py                       # NEW: /brief command group
    └── ...
```

---

## Dependencies (pyproject.toml additions)

```toml
[project.optional-dependencies]
brief = [
    "httpx>=0.27.0",              # For GitHub/GitLab API
    "pygithub>=2.0.0",            # GitHub SDK (optional, can use raw API)
    "gitpython>=3.1.0",           # Git operations (if not already included)
    "sentence-transformers>=3.0.0",  # Local embeddings (optional)
    "chroma-client>=0.5.0",       # Vector store (optional)
]
```

---

## Appendix: Command Reference

### CLI Commands

```bash
# Initialize BRIEF for a repository
ite brief init

# Index all commits
ite brief index --all

# Index last 100 commits
ite brief index --last 100

# Run full review on staged changes
ite brief review --staged

# Run full review on last commit
ite brief review --last

# Search the Ledger
ite brief search "why sessions expire"

# Generate onboarding for new developer
ite brief onboard --dev john

# Check promise fulfillment
ite brief promises --check

# List all rules
ite brief rules

# Pre-mortem analysis
ite brief pre-mortem --feature "add caching"

# Export all decisions
ite brief export --format json
```

### Slash Commands (in ite REPL)

```
/brief ask Why do we use PostgreSQL?
/brief pre-mortem adding real-time notifications
/brief promises
/brief decisions
/brief incidents
/brief rules
/brief onboarding
/brief extract
/brief init
```

---

## Closing

This specification should allow any competent engineer to build BRIEF in 6 weeks. The key principles:

1. **Git is the source**: Don't try to replace git, augment it
2. **Memory over rules**: Remember decisions, don't just enforce patterns
3. **Personality matters**: Warnings are useless if nobody reads them
4. **Local-first**: No cloud required, no vendor lock-in
5. **Earn trust**: False positives destroy credibility

Build it. Then watch your future self thank you.

*It's based.*

---

*Document Version: 1.0*  
*Created: 2024*  
*For: iTE (Interactive Terminal Environment)*