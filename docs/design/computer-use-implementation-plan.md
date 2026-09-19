# Computer Use for iTE — Implementation Plan

**Status:** Draft for review
**Owner:** David
**Last updated:** 2026-09-19
**Related:** `docs/design/SPEC-BRIEF.md`, `AGENTS.md`

---

## 1. Goal

Let iTE operate the user's computer directly: see the screen, decide on a target,
click and type, and confirm the action took effect. The intelligence layer is
TypeSafe's Jev, used as a judgment primitive — not as the thing that sees.

### Non-goals (v1)

- **Not a screenshot-to-action vision agent.** Vision is a fallback tier, not the
  primary sensor.
- **Not autonomous long-horizon task execution.** v1 executes one user-directed
  intent per turn with verification, not multi-hour goals.
- **Not cross-platform on day one.** macOS first. Windows/Linux are Phase 6 and
  the design keeps the seams for them.
- **Not unattended by default.** Auto mode is opt-in, bounded, and reversible-only
  until the eval numbers justify more.

---

## 2. The constraint that shapes everything

**Jev cannot see.** `jev-1.13` input is text only — string, JSON object, or array
of text. No image, audio, or video input ([Models](https://docs.typesafe.ai/models)).
So "look at the frame and find the text" is not a Jev job, and no prompt makes it
one.

This is a benefit, not a limitation. Localizing text on screen has a better,
deterministic answer than a model, and Jev is freed to do the part that is
genuinely judgment. Two of the three perception tiers need no model at all.

**Corollary rule for the whole design:** Jev chooses *which candidate*, never
*where it is*. It returns an option key; code looks up the box. Jev never emits,
receives, or reasons about coordinates.

---

## 3. Architecture

```
        ┌──────────────────────────────────────────────────┐
        │                    CODE LOOP                     │
        │         (owns control flow + execution)          │
        └──────────────────────────────────────────────────┘
                              │
   ┌──────────────────────────┼──────────────────────────┐
   ▼                          ▼                          ▼
┌──────────┐            ┌───────────┐             ┌───────────┐
│ OBSERVE  │            │  SELECT   │             │   VERIFY  │
│  (code)  │──candidates│   (Jev)   │──target id──│   (Jev)   │
└──────────┘   + id     └───────────┘      │      └───────────┘
   ▲                                        ▼            │
   │                                   ┌─────────┐       │
   │                                   │   ACT   │       │
   │                                   │ (code)  │       │
   │                                   └─────────┘       │
   │                                                     │
   └────────── RECOVERY (Jev) on failure / no-op ────────┘
```

| Stage | Owner | Rationale |
|---|---|---|
| Capture + normalize | **Code** | Deterministic. No model can do it better or cheaper. |
| Target selection | **Jev** (`Choice`) | Best-in-class shape: pick one of N enumerated options. |
| Gates | **Jev** (`Noul`) | Cheap calibrated yes/no over the same state. |
| Severity / approval routing | **Jev** (`Score`) | Ordered rubric → maps to approval policy. |
| Execution | **Code** | Model must never hold authority over side effects. |
| Verification | **Jev** (`Noul`) | Cheapest way to catch silent GUI failures. |
| Recovery | **Jev** (`Choice`) | Bounded action selection on failure. |

---

## 4. Perception

### 4.1 Three tiers, cheapest first

**Tier 1 — Accessibility tree (primary).**
The OS already exposes every window as structured elements: role, exact string,
position, size, enabled/focused state, supported actions. Strictly better than
OCR where it exists — no recognition error, exact geometry, and it tells you
*what is clickable*, which OCR never can.

- macOS: `AXUIElement` via `pyobjc-framework-ApplicationServices` /
  `pyobjc-framework-Quartz`. Requires the **Accessibility** permission.
- Windows: UIAutomation (Phase 6) · Linux: AT-SPI (Phase 6)

**Tier 2 — OCR with bounding boxes (fallback).**
For canvas, Electron, remote desktop, games — anything where AX returns nothing.
iTE already has half of this: `ReadImageTool` calls
`pytesseract.image_to_string(image)` at `src/ite/tools/builtin/media_tools.py:503`,
which discards geometry. The fix is the adjacent API:

```python
data = pytesseract.image_to_data(image, output_type=Output.DICT)
# per word: left, top, width, height, conf, text
```

`conf` lets us drop low-confidence noise. **Trap:** these are *pixel* coordinates.
Retina is 2×, so logical point = `(left + width/2) / scale`. Do that division in
code — Jev does no arithmetic reliably (documented failure mode: *Math and numbers*).

**Tier 3 — Vision model (last resort).**
"Icon-only buttons", "the blue submit control", charts, image content. Genuinely
visual, needs a multimodal *generative* model — a **second model in the loop**.
Never routed through Jev.

### 4.2 Normalization contract

Every tier must emit the same shape, in **logical points, global screen space**.

```python
@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

@dataclass(frozen=True)
class Candidate:
    id: str              # stable per-observation key, e.g. "c07"
    text: str            # label / value / accessible name
    role: str            # AX role, or "text" for OCR
    box: Rect            # logical points, global
    source: str          # "ax" | "ocr" | "vision"
    confidence: float    # OCR confidence, or 1.0 for AX
    enabled: bool = True
    clickable: bool = False
    focused: bool = False
    sensitive: bool = False   # from AX role (e.g. AXSecureTextField)
```

```python
@dataclass(frozen=True)
class Observation:
    observation_id: str
    app_name: str
    window_title: str
    screen: tuple[int, int]        # logical size
    scale: float                   # backing scale factor
    captured_at: float
    frame_hash: str                # perceptual/md5 for no-op detection
    candidates: list[Candidate]
    tier_used: str
```

**Mutable candidate set.** `computer_do` may only target `clickable and enabled`
candidates. A label that isn't actionable is never a valid actuation target —
enforced in code before Jev is even asked.

### 4.3 Change detection

`frame_hash` gates the loop: if the screen did not change after an action, that is
a **no-op**, which is a failure signal, not a success. Cheap, deterministic, and
prevents the classic computer-use failure of silently clicking into the void.

### 4.4 Candidate budget

Cap candidates sent to Jev. Above a threshold (start at **120**), pre-filter in
code by token overlap / fuzzy match between intent and candidate text, then Jev
selects from the shortlist.

> ⚠️ **The pre-filter is a recall risk** — if the true target is filtered out, Jev
> can never pick it. It must be measured, not assumed. Track shortlist-recall in
> the eval harness and prefer a generous threshold.

Also note the documented failure mode: *"Large state full of irrelevant detail"* —
unrelated content acts as a distractor and costs accuracy. Prefer truncated labels
(first ~60 chars) plus role, and expand only in stage 2.

---

## 5. The Jev layer

### 5.1 Stage 1 — select + gate (one request, parallel)

Follows the [`skill_suggestion`](https://docs.typesafe.ai/cookbooks/skill_suggestion)
shape: a `Choice` to pick, plus gate `Noul`s to decide whether to act at all.
These are independent questions over the same state and run in parallel.

```python
state = {
    "intent": user_intent,
    "app": app_name,
    "window": window_title,
    "screen_text": screen_text,          # delimited, labelled as DATA (see §7.6)
    "candidates": [
        {"id": "c00", "text": "...", "role": "AXButton", "enabled": True},
        ...
    ],
}

questions = {
    "target": choice(
        instructions=(
            "Which candidate is the control the user's intent refers to? "
            "Choose exactly one id from `candidates`. Choose `none` if no candidate "
            "matches."
        ),
        criteria={
            **{c["id"]: f'{c["role"]}: {c["text"]}' for c in candidates},
            "none": "No candidate matches the intent",
        },
    ),
    "target_present": noul(
        instructions="Is the target the intent refers to among the listed candidates?",
    ),
    "needs_actuation": noul(
        instructions=(
            "Does fulfilling this intent require clicking or typing, rather than "
            "only answering the user?"
        ),
    ),
    "is_sensitive": noul(
        instructions=(
            "Is the target a credential, payment, 2FA, permission, or destructive "
            "control?"
        ),
    ),
    "reversible": noul(
        instructions="If this action executes, can its effect be undone?",
    ),
}
```

**Code-side consumption:**

```python
if ans["target_present"].noul < PRESENT_T   : abort("target not found")
if ans["target"].choice == "none"           : abort("no candidate matched")
target = candidate_by_id[ans["target"].choice]   # code owns the box
```

`PRESENT_T` starts at **0.5** and is tuned on real traces. Do not carry a threshold
tuned on a `Noul` over to a `Choice` — the docs are explicit that these answer
different questions and are not arithmetically comparable.

### 5.2 Stage 2 — disambiguate (conditional)

Triggered only when `confidence` is low or the top-2 probabilities are close
(start: margin < 0.25). Re-ask with the top 3–5 candidates expanded with full text,
role, and nearby context.

This is the two-stage structure the cookbook uses: skim everything cheaply, then
spend detail only on the finalists.

### 5.3 Severity → approval routing

```python
"severity": score(
    instructions="How consequential is executing this action?",
    criteria=[
        "Trivial and reversible (navigation, focusing a field)",
        "Routine (submitting a form, sending a message)",
        "Consequential (deleting content, sending money, changing settings)",
        "Irreversible or destructive (purchases, permanent deletion)",
    ],
)
```

`score` maps to `CommandSafety.SAFE / CAUTION / DANGEROUS` and therefore to the
existing approval path.

### 5.4 Verification (post-act, mandatory)

Re-capture and ask:

```python
"took_effect": noul("Did the screen change in the way the intent required?"),
"appears_blocked": noul("Is a dialog, error, or loading state blocking progress?"),
```

For typing, OCR the target region and ask whether the field now contains the
expected value. A failed verification is a first-class outcome — it triggers
recovery, not silent success.

### 5.5 Recovery

```python
"recovery": choice(
    instructions="What should happen next?",
    criteria={
        "wait_and_recheck": "The app may still be responding",
        "relocate_target": "The target moved or re-rendered",
        "scroll_and_retry":  "The target is likely off-screen",
        "escalate_to_user":  "A human should take over",
        "abort":             "Stop; this is not proceeding safely",
    },
)
```

Bounded: max consecutive failures (start 3) → hard stop and escalate.

### 5.6 Jaggedness guardrails (from Jev 1.13 docs)

| Jev weakness | Rule in this design |
|---|---|
| Math, counting | All arithmetic, scaling, and counting in code |
| Coordinates / numeric precision | Jev returns option keys only |
| Date/time comparison | Never asked; code compares timestamps |
| Colour / hex values | Never asked; pass named colours via vision tier |
| Indirection, multi-hop | One narrow judgment per question |
| Large distracting state | Truncated labels; shortlist above 120 candidates |
| Adversarial content | Structural allowlist + data labelling (§7.6) |
| Contradictory criteria | Criteria written as an extension of the instruction |
| Generation | Jev never generates text; vision model handles that |

### 5.7 Confidence semantics

`Choice`/`Score` `confidence` is **distribution concentration**, not correctness.
A `Noul` near 0.5 is genuine uncertainty, not "medium intensity". Several
acceptable options can also spread the distribution, so low confidence does not
automatically mean stop.
- `target_present` low → abort (safe default).
- `target` confidence low → stage-2, then escalate if still low.
- Ignore uncertainty on branches we are not taking.

---

## 6. Actuation

Input injection behind a lazy-loaded optional dependency (`pyobjc` Quartz
`CGEvent` on macOS). Actions, in rising risk order:

| Action | Mechanism | Risk |
|---|---|---|
| `move` / `click` | `CGEvent` mouse events at logical point | Low |
| `double_click` | two click events | Low |
| `type_text` | `CGEvent` keyboard events | Medium |
| `key` (Return, Esc, Tab, arrows) | keycode events | Medium |
| `scroll` | scroll wheel events at point | Low |
| `drag` | mouse down → move → up | Medium |

**Preferred path where AX supports it:** use AX actions (`AXPress`, set
`AXValue`) instead of synthesizing raw events. More reliable, more semantic, and
often works when raw event injection is blocked.

**The target is always resolved fresh.** A confirmation is captured against an
observation; if `frame_hash` changed between selection and execution, **re-resolve**
rather than click a stale coordinate. This is a TOCTOU guard and it matters.

---

## 7. Safety model

This is the part that decides whether the feature is defensible. Screen text is
attacker-controlled, and the action space is now the entire desktop.

### 7.1 Capability gating

- Config flag `computer_use.enabled` — **default `false`**.
- Actuation is disabled while `computer_use.act_enabled` is false (observe-only).
- Off entirely in plan mode — comes free, since `computer_do` is `ToolKind.SHELL`,
  and `is_mutating()` (`src/ite/tools/base.py:200-206`) makes
  `allowed_in_plan_mode = False`.

### 7.2 Two tools, no enum changes

| Tool | `ToolKind` | Approval | Purpose |
|---|---|---|---|
| `computer_look` | `READ` | none | Capture + candidates. Safe, free, always allowed. |
| `computer_do` | `SHELL` | via `get_confirmation` | Execute one action against one candidate. |

`ToolKind` has no UI kind, and adding one would ripple through `is_mutating`,
`risk_by_kind` (`base.py:210-217`), and the UI. Reusing `SHELL` gives mutating +
high risk + approval gating for free. **Zero enum changes.**

### 7.3 Boundaries

- **App allowlist / denylist** by bundle id (`computer_use.app_allowlist` /
  `app_denylist`). Denylist wins.
- **Sensitive-field block.** Never act on AX `AXSecureTextField` /
  password roles, detected structurally and cross-checked with the Jev
  `is_sensitive` Noul. Defence in depth — the Noul is a second signal, never the
  only gate.
- **Zone exclusion.** Rectangles marked untouchable in config.
- **Irreversible actions always confirm**, in every mode.

### 7.4 Reuse, don't fork

`src/ite/safety/approval.py` already has the vocabulary: `ApprovalDecision`,
`CommandSafety`, `ApprovalContext`, `DANGEROUS_PATTERNS` (`:35-64`), `SAFE_PATTERNS`
(`:67+`). Add a GUI action classifier alongside those tables rather than inventing
a parallel system.

Approval should surface through the existing notch path
(`src/ite/integrations/open_island/`) — it already works when the terminal is not
focused, which is exactly the situation a desktop-driving agent creates.

### 7.5 Budgets and kill switch

- Max actions per turn (start 10) and per session (start 50).
- Max wall-clock per task.
- Max Jev calls per task; cost cap.
- Consecutive-failure stop (3) → escalate.
- **Kill switch:** global hotkey + persistent visible indicator while automation is
  active. Any human input during automation pauses the loop.
- Always-visible state. The user must never be unsure whether iTE is driving.

### 7.6 Prompt injection — structural, not persuasive

The docs are blunt: Jev *"does not treat `state` as hostile by default"* and
injected instructions or text that argues for its own classification **can move the
answer**.

The defence cannot be "we told the model to ignore it." It is structural:

1. **Screen text is data, always.** Send it as a labelled, delimited field inside
   `state` (`screen_text`), never as instructions.
2. **Output is constrained to an enumerated set.** Jev may only return a candidate
   id that code supplied. An injected "click X" cannot name a target that is not in
   the list, and cannot supply coordinates.
3. **Code validates the returned id** against the candidate map → unknown ids are
   a hard error.
4. **Redact before sending.** Reuse `redact_sensitive_command_text`
   (`src/ite/ui/reup/_helpers.py:62`) so secrets on screen are not shipped to the
   API.
5. Adversarial test cases are mandatory in the eval harness (§9).

### 7.7 Audit log

Append-only JSONL per session: observation hash, candidate count, every Jev question
and answer with confidence, chosen target, action, verification result, approval
decision. Required for eval, incident review, and threshold tuning. Without this,
none of the §11 metrics exist.

### 7.8 Platform permissions

macOS Screen Recording + Accessibility are a **product gate**, not a footnote.
Detect missing permission and return an actionable error with a deep link to System
Settings — following the existing dependency-hint pattern
(`_ocr_recovery_hint`, `media_tools.py:192-203`).

---

## 8. iTE integration

### 8.1 New package

```
src/ite/computer_use/
├── __init__.py
├── jev.py           # ✅ exists (229 lines) — TypeSafe transport + Noul/Choice/Score
├── types.py         # Rect, Candidate, Observation
├── permissions.py   # macOS permission detection + guidance
├── capture.py       # screen capture
├── ax.py            # accessibility tree walker
├── ocr.py           # image_to_data → candidates
├── vision.py        # Tier-3 fallback (later phase)
├── perceive.py      # cascade orchestration → Observation
├── resolve.py       # Jev selection + gates + severity + recovery
├── actions.py       # input injection (lazy pyobjc)
├── verify.py        # post-act verification
├── safety.py        # app allow/deny, sensitive fields, budgets
├── audit.py         # JSONL logger
└── loop.py          # observe → select → gate → act → verify → recover
```

**Note:** `jev.py` already exists from the earlier session. It is the Phase-2
transport foundation and should be reviewed/refined rather than rewritten. It is
currently **not** wired into anything.

### 8.2 Tool registration

Follow the established pattern exactly:

1. New module `src/ite/tools/builtin/computer_use.py` with `ComputerLookTool` and
   `ComputerDoTool`.
2. Imports in `src/ite/tools/builtin/__init__.py:1-46`.
3. Append to `__all__` (`:48-95`).
4. Append to `get_all_builtin_tools()` (`:98-146`).

**Ripple check:** no test asserts on total tool count (verified by grep across
`tests/`), so adding two tools is safe.

Tool descriptions are tight and cheap because `_get_tool_guidelines_section`
(`src/ite/prompts/system.py:657-736`) enumerates every registered tool into the
system prompt, and `compact_description()` truncates to the first sentence when the
optimizer is enabled. **Lead with the sentence that matters.**

Note this also means the +2 tools are paid for on every turn — see §10.

### 8.3 Config

Add `ComputerUseConfig` to `src/ite/config/config.py`, wired through the existing
workspace-aware TOML layering in `src/ite/config/loader.py`:

```toml
[computer_use]
enabled = false
act_enabled = false
auto_act = false                    # opt-in; reversible-first
app_allowlist = []
app_denylist = []
max_actions_per_turn = 10
max_actions_per_session = 50
max_consecutive_failures = 3
candidate_cap = 120
vision_fallback = false
jev_model = "jev-1.13.0"            # pin, don't use an alias
```

**Pin the versioned ID, not `jev-latest`.** Docs: an alias moves when a release
ships, so answers can change without a change on our side. If thresholds are tuned
against `jev-1.13.0`, moving models must be deliberate.

API key from `TYPESAFE_API_KEY` (never in config files).

### 8.4 Policy

Add `computer_do`-specific redirects to `ToolSelectionPolicy`
(`src/ite/tools/policy.py:20-207`):
- Prefer `computer_look` before `computer_do` — nudge toward observe-first.
- Block `computer_do` when no observation exists in the current turn.
- Reuse the existing plan-mode mutation block.

### 8.5 Dependencies (all optional/lazy)

| Package | Platform | Purpose |
|---|---|---|
| `pyobjc-framework-Quartz` | macOS | capture + `CGEvent` injection |
| `pyobjc-framework-ApplicationServices` | macOS | AX tree |
| `Pillow` | any | ✅ present |
| `pytesseract` | any | ✅ present (needs `tesseract` binary) |

Lazy-load via the existing `_module_available` pattern
(`media_tools.py:56`) and return recoverable errors with install hints. **No new
hard dependency.**

---

## 9. Testing strategy

### 9.1 Unit tests (CI-safe, no permissions, no network)

Follow `tests/test_media_tools.py` conventions: `IsolatedAsyncioTestCase`,
`Config(cwd=cwd, api_key="test")`, `ToolInvocation(params=..., cwd=cwd)`, and
`unittest.mock.patch` of the lazy-load helpers.

Mock both perception and Jev. Cover:
- Candidate normalization, OCR pixel → logical-point scaling, Retina 2×.
- Sensitive-field detection blocks actuation regardless of the Jev answer.
- `target_present` below threshold → abort.
- Out-of-set `target` id → hard error (injection attempt).
- `frame_hash` unchanged → no-op detected, recovery invoked.
- Budgets stop the loop; kill switch honoured.
- Tool registration: both tools present, `computer_look` non-mutating,
  `computer_do` mutating + high risk + not allowed in plan mode.
- Malformed/missing Jev response → clean recoverable error.

### 9.2 Fixture-based eval harness

Recorded JSONL of `(observation candidates, intent, expected target id, expected
outcome)`. Offline, no screen needed. Produces the §11 metrics and is the basis for
threshold tuning and regression detection.

Must include **adversarial fixtures**: screen text containing injected instructions,
fake "system" messages, and candidates whose labels argue for their own selection.

### 9.3 Permission-gated tests

Golden screenshots for perception regression. Skipped in CI when permissions are
absent — never make CI depend on Screen Recording.

---

## 10. Cost and latency

**Measured reality, not marketing:** the `skill_suggestion` cookbook measured
**90–310ms** for a 182-option `Choice`. TypeSafe documents real-time as ~150ms.
Budget p95 ≈ 300ms per Jev call, and note stage-1 + verify = **2 calls minimum per
action**, more with stage-2 and recovery.

**Cost:** `jev-1.13.0` is $42 per Btok ($0.000042 per 1k tokens), output tokens
free. The headline "$0.0001 per call" implies ~2,400 tokens; a candidate list with
per-candidate criteria will land nearer **$0.0002–$0.0006 per call**. Cheap enough
for per-turn routing, but at ~3 calls × ~15 steps that is ~$0.01–$0.03 per task.
Track it; don't quote the marketing number.

**Build-flag warning:** the docs state rate limits (250k tok/s, 1200 rpm) are
**adjusting dynamically and can change without notice**. Handle `429`/`529` with
backoff (already in `jev.py`), and degrade gracefully — never let a Jev rate limit
brick the loop.

**Per-turn tax:** the +2 tools are advertised in the tool list *and* enumerated in
the system prompt on every turn (AGENTS.md / `system.py:657-736`). Keep descriptions
to one tight sentence.

---

## 11. Metrics

| Metric | Why | Initial target |
|---|---|---|
| Target-selection top-1 accuracy | Core quality | measure, then improve |
| **Wrong-actuation rate** | **Critical.** Acting on the wrong thing | near zero; hard gate |
| Needless-actuation rate | Acting when it shouldn't | low |
| Shortlist recall (when pre-filtering) | Guards the §4.4 recall risk | ≥99% |
| Post-act verification pass rate | Loop honesty | high |
| Steps per task | Efficiency | trending down |
| Latency p50/p95 per stage | UX viability | p95 < 300ms/Jev call |
| Jev tokens + $ per task | Unit economics | tracked |
| Escalation rate to human | Autonomy ceiling | informative |

The `skill_suggestion` cookbook gives a useful benchmark shape: it cut wrong picks
16.8% → 7.3% against a 2.5% oracle floor, and **7 cases the agent had right were
broken by a confident suggestion** — which is exactly why Jev is a *suggester*, never
the authority.

---

## 12. Phases

### Phase 0 — Spikes (timeboxed)
De-risk before committing. Each produces a written finding + measured number.
- Does AX expose usable trees for the target apps? Coverage rate?
- Capture method: ScreenCaptureKit vs `CGWindowListCreateImage` vs `screencapture`
  (note: `CGWindowListCreateImage` is deprecated on macOS 14+).
- `image_to_data` box quality and `conf` distribution.
- Measured Jev latency and token cost on a realistic candidate list.
**Exit:** a decision on capture API and an honest AX coverage number.

### Phase 1 — Perception + observer (read-only)
`types.py`, `capture.py`, `ax.py`, `ocr.py`, `perceive.py`. `computer_look` tool.
No Jev, no injection. Dumps `Observation` JSONL.
**Exit:** can enumerate real candidates with coordinate accuracy verified by hand.

### Phase 2 — Jev resolver, dry-run
`resolve.py` + `jev.py`. `computer_do` resolves a target and **logs only**.
Build the eval harness and adversarial fixtures.
**Exit:** top-1 accuracy measured and wrong-actuation rate ≈ 0 on fixtures.

### Phase 3 — Actuation behind a flag
`actions.py`, `safety.py`, `audit.py`. Reversible actions only, approval on every
action. TOCTOU re-resolve guard.
**Exit:** real tasks completed with a human approving each step.

### Phase 4 — Verification + recovery
`verify.py`, `loop.py` recovery path, frame-hash no-op detection.
**Exit:** silent failures become visible failures.

### Phase 5 — Auto mode, bounded
Budgets, denylists, kill switch, irreversible-always-confirm. Opt-in.
**Exit:** unattended reversible tasks; metrics from §11 defensible.

### Phase 6 — Cross-platform + tool-selection payoff
Windows UIA / Linux AT-SPI behind the same `Candidate` contract. Then apply the
same enumerate → select → gate engine to the **tool roster** (the
`agent.py:1572` hook from the earlier discussion) — same machinery, different
candidate set.

---

## 13. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| AX coverage gaps | Blind spots | OCR/vision cascade; measure coverage in Phase 0 |
| macOS permission friction | Adoption | Clear in-product onboarding + actionable errors |
| Non-deterministic GUI loop | Silent wrong action | Verification mandatory; wrong-actuation is a hard gate |
| Prompt injection from screen | Hijack | Structural allowlist (§7.6), redaction, adversarial fixtures |
| Cost at scale | Unit economics | Budgets + caps + measured $/task |
| Dynamic rate limits | Bricked loop | Backoff + graceful degradation |
| Jev jaggedness | Bad judgments | §5.6 guardrails; keep math/coords/counting in code |
| Third-party ToS | Legal | Audit log; per-app allowlist is opt-in |
| Perception latency | UX | Cascade cheapest-first; cache AX tree per frame |
| Uncertainty on `Noul` ≈ 0.5 | False confidence | Never treat 0.5 as "medium" (§5.7) |

---

## 14. Open questions

1. **macOS-only for v1?** Plan assumes yes; confirm.
2. **Vision fallback provider** — main chat model, or a separate dedicated one?
3. **Auto mode default** — plan says off. Confirm.
4. **First dogfood app** — iTE's own UI is a safe, self-contained first target.
5. **`computer_do` vs `computer_act`** naming preference.
6. **Does `jev.py` stay as written**, or be reviewed/refined in Phase 2?
7. **Whose TypeSafe account / key** for dev, and is there a spend cap on it?

---

## 15. Definition of done (v1)

- `computer_look` and `computer_do` registered, tested, and passing ruff + mypy + pytest.
- Observe-only works with zero config beyond the macOS permission.
- Actuation is disabled by default and gated by approval when enabled.
- Every action is verified; every step is audit-logged.
- Eval harness reports §11 metrics on fixtures including adversarial cases.
- Wrong-actuation rate on the fixture set is zero.
- All CI tests pass **without** screen permissions.
