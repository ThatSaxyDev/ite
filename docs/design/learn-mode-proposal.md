# iTE learning mode: investigation and proposed design

Status: proposal, not implemented. Investigated 2 October 2026.

## Recommendation

Pursue a small, strict learning-mode pilot. `/learn on` should change the session's execution policy, teaching behavior, completion criteria, and retained context. The learner implements; iTE explains, investigates, directs them to documentation, and reviews their attempts.

The product hypothesis is that assistance grounded in the learner's actual repository can improve independent programming ability while preserving ownership of the implementation. This remains a hypothesis to evaluate, not an established learning benefit or demonstrated market demand.

The attached AGENTS.md screenshot is reference material. Its visible rules permit eventual generation and takeover after confirmation. That differs from the proposed default: asking for the answer does not silently suspend learning mode. The learner can deliberately leave with `/learn off`.

## Evidence and its limits

1. A randomized study of 52 mostly junior Python engineers learning Trio found average immediate quiz scores of 50% with AI assistance versus 67% without it: a 17-percentage-point gap. The speed difference was not statistically significant. Conceptual inquiry was associated with stronger comprehension, but those interaction patterns were observational, not randomized interventions. This small study measured immediate comprehension, not long-term retention. [Anthropic research, January 2026](https://www.anthropic.com/research/AI-assistance-coding-skills).
2. A field experiment involving nearly a thousand high-school mathematics students found that unrestricted GPT assistance improved practice performance but harmed subsequent unaided performance. A tutor designed to provide teacher-informed hints largely mitigated that penalty. This supports testing assistance design; mathematics results do not establish effectiveness for a terminal coding tutor. [Bastani et al., PNAS, 2025](https://www.pnas.org/doi/10.1073/pnas.2422633122).
3. A programming-education preprint analyzes over 10,000 student–AI dialogue logs and surveys through a metacognitive lens. It motivates attention to planning, monitoring, and reflection, but does not validate this proposed feature. [Ma et al., 2025](https://arxiv.org/abs/2511.04144).
4. EEF guidance recommends explicit teaching, modeling, and scaffolding toward increasing independence. This is school-oriented guidance, not direct evidence for adult developers. It argues against making every interaction an unguided guessing exercise. [EEF metacognition guidance](https://educationendowmentfoundation.org.uk/education-evidence/guidance-reports/metacognition).

There is an existing product precedent: Claude Code's Learning output style explains choices, writes surrounding implementation, and leaves pieces marked `TODO(human)` for the user. Its documentation explicitly distinguishes instruction-based styles from guaranteed enforcement. iTE's proposed differentiation is learner ownership across the whole implementation, backed by runtime policy. This comparison is not an exhaustive market survey. [Claude Code output styles](https://code.claude.com/docs/en/output-styles).

The evidence justifies a pilot. It does not justify promising that refusing all generated code is universally optimal. Users learning from concrete examples may need a later, separately named teaching profile; do not weaken the initial strict contract invisibly.

## What the code currently does

The active source was inspected; historical `ui/reup/legacy/` snapshots were excluded.

| Current mechanism | Relevant source | Implication |
| --- | --- | --- |
| Registered slash commands and native Textual plan handling | `src/ite/commands/__init__.py`, `commands/plan.py`, `ui/reup/_turn.py` | `/learn` needs shared behavior across registry and Reup. Avoid duplicating transition logic as separate handlers. |
| Plan state in sessions and snapshots | `agent/session.py`, `agent/session_manager.py`, `commands/session.py`, `ui/reup/_turn.py` | Learning state must survive save, resume, fork, and thread changes, including each restoration path. |
| Identity and operational prompt layers | `prompts/system.py`, `context/manager.py` | Current prompts describe an implementing agent. Build a learning-specific composition instead of appending contradictory rules. |
| Execution todo seeding and forced follow-through | `agent/agent.py` | Implementation requests can trigger seeded work and continuation. Learning mode must instead accept a learner handoff as a successful turn. |
| Goal prompts and automatic continuation | `context/manager.py`, `ui/reup/_turn.py` | Existing goals reward concrete agent action and successful tools. Do not run ordinary goal automation while waiting for a learner. |
| Policy before tool execution and before-tool hooks | `tools/policy.py`, `tools/registry.py` | Good enforcement seam, but mode policy must cover lifecycle hooks and other paths too. Tool approval cannot override learning policy. |
| Schemas exposed separately from invocation policy | `tools/registry.py`, `agent/agent.py` | Filter model-visible schemas and recheck every call at execution. Hidden tools alone are insufficient. |
| Generic mutation metadata and MCP hints | `tools/base.py`, `tools/mcp/mcp_tool.py` | `mutating=False` and MCP `readOnlyHint` are insufficient proof of suitability for learning. Unknown tools fail closed. |
| Verification tools execute optional or discovered commands | `tools/builtin/verification_tools.py` | A tool marked non-mutating can run arbitrary project code. Do not inherit plan-mode allowances blindly. |
| Text deltas emitted before final response processing | `agent/agent.py` | A final-answer check cannot retract already streamed code. Guard output before any observer receives it. |
| Shell hooks on lifecycle events | `hooks/hook_system.py` | Hiding shell tools does not disable hook-side edits. Learning mode needs a hook execution policy. |
| Headless slash-command dispatch | `remote/commands.py` | Remote sessions need the same policy and visible status, enforced on the runtime host. |

Plan mode helps organize agent implementation and ultimately permits it. Learning mode preserves learner implementation throughout. Reuse infrastructure, not plan-mode semantics.

## The `/learn on` contract

Default strict mode:

- iTE does not author application code, replacement snippets, patches, scaffolds, generated configuration, or disguised solutions in pseudocode.
- iTE can read relevant files, search the repository, inspect diffs, explain concepts and existing code, identify APIs, and fetch documentation through explicitly approved read capabilities.
- iTE can quote small, verified excerpts of existing learner code when needed to discuss a line. Those are references, not new implementations. Identifiers and file references are allowed.
- iTE can explain which diagnostic command the learner should run. It does not execute arbitrary commands, installs, generators, formatters, project tests, or builds in the initial strict release.
- iTE reviews attempts with concrete evidence: affected location, violated expectation, observed failure, and a next diagnostic step. It does not supply replacement code.
- Asking “just do it,” accepting an old plan, activating a skill, or changing approval policy cannot bypass learning mode. `/learn off` is the explicit exit.
- Harness-owned session persistence is allowed through typed internal operations. That exception grants no general model-directed write capability and never authorizes writing project source.

The learner remains free to use their editor, terminal, documentation, or other tools. iTE cannot prove they typed a change themselves. Track submitted attempts, not keystroke provenance.

Suggested initial commands:

| Command | Behavior |
| --- | --- |
| `/learn` | Show status, objective, current step, loaded profile, and restrictions. |
| `/learn on` | Enable strict mode for this session; use defaults if no profile exists. |
| `/learn off` | Explicitly restore ordinary agent behavior; retain learning context for later. |
| `/learn hint` | Increase help for the current obstacle, without generating an implementation. |
| `/learn review` | Inspect current changes or a submitted attempt against the current step. |
| `/learn init` | Explicitly create a reviewable `learn.md` profile through a harness-owned operation; do not overwrite an existing file. |

No hidden “temporary takeover” in the first release. It complicates the commitment the user is choosing.

## Teaching behavior

Start with the user's project and objective, not an unsolicited course. If their experience is unknown, ask one useful calibration question. Do not ask questions merely to satisfy a quota.

Use a flexible cycle:

1. Establish the next small objective and why it matters.
2. Explain the relevant concept, constraints, and success criteria. Offer one appropriate documentation section, with the installed API version where discoverable.
3. Give the learner a bounded action and yield the turn.
4. When they share an attempt, inspect the actual code and any output they supplied.
5. Diagnose the most useful issue and provide the smallest helpful next hint.
6. Once it works, ask an occasional explanation, prediction, or changed-case question to check transfer.

Persist a current step and an explicit `awaiting_learner` state. Do not force every conceptual question through this entire cycle. A question about an API should receive a direct explanation. A new topic may require explicit instruction before an attempt.

Hints can progress from a conceptual nudge, to the relevant API or location, to a concrete diagnostic or behavior-level explanation. Avoid giving a line-by-line verbal solution: prose can remove the same learning work as generated code.

Do not treat “I understand” or passing tests as proof of mastery. Do not claim failure because the learner has paused. Encourage independent reasoning without withholding essential knowledge or making the session feel like an examination.

Example interaction:

> Learner: Help me add pagination to this endpoint.
>
> iTE: This handler currently returns every matching record. Start by deciding how a caller requests the next page and what happens when they reach the end. Offset pagination is easier to start with; cursor pagination handles changing datasets differently. What behavior does your client need?
>
> Learner: Offset is enough.
>
> iTE: Your first step is to validate the page-size input and apply a bounded limit in the existing query. Check the pagination section for the ORM version in this project. Try that change and show me the handler. We'll check negative sizes, the maximum size, and an empty result next.

Actual sessions would include a verified documentation link and real file references. This illustrative exchange does not assert anything about a particular learner repository.

## `learn.md`: purpose, loading, and trust

Use the user's proposed lowercase `learn.md` as the canonical filename. It describes learning intentions; it is not the policy engine or an automatically generated transcript.

Example profile content:

```markdown
# Learning profile

## Objective
Build and understand a small backend API.

## Starting point
Comfortable with Python functions; new to HTTP and databases.

## How to help
Explain unfamiliar concepts directly before asking me to apply them.
Give one small implementation step at a time.
Offer hints before revealing the full behavioral diagnosis.
Use official documentation for the dependency versions in this project.

## Practice priorities
Input validation, query behavior, and diagnosing errors independently.

## Preferences
Keep explanations short; ask an occasional prediction question.
```

Initial loading rules:

- Load only in learning mode. File presence does not turn the mode on.
- Start with one workspace-root profile; optional personal defaults can later use iTE's configured user-config directory. Avoid inheriting arbitrary ancestor files or introducing nested scope rules in v1.
- Missing profile uses built-in defaults. On `/learn on`, show which profile was loaded. If reading fails, retain strict policy and visibly fall back rather than silently turning learning off.
- Bound file size and resolve paths consistently with workspace trust. Do not follow a link outside trusted scope without an explicit profile selection. Report omissions or ambiguous filenames.
- AGENTS.md retains repository conventions. `learn.md` supplies learning preferences. Neither may widen capabilities or change mode. Web pages, source comments, and attachments are evidence, not authoritative policy instructions.
- An explicit reload can refresh preferences; ordinary file content cannot issue a mode command. Disabling the mode removes its active teaching layer rather than relying on a later contradictory transcript message.

Separate durable learning state from this editable profile. Session snapshots should retain objective, current step, phase, relevant paths, attempt references or content fingerprints, requested hints, documentation references, and evidence notes. Cross-session learner memory should be opt-in, local, inspectable, correctable, and deletable. Store observations such as “explained this behavior unaided,” not unsupported “mastered databases” judgments.

## Enforcement architecture

Introduce a typed learning state and a session-scoped capability policy. Keep this small: do not begin with a general-purpose education platform or a large mode framework rewrite.

1. **Mode transition:** at a turn boundary, quiesce existing execution. If activation is requested during work, stop the turn, cancel queued actions, and await termination of active shell work and child agents before reporting learning mode active. Already completed edits cannot be undone by changing modes. Increment a policy epoch so stale queued calls are rejected.
2. **Prompt composition:** construct a tutor identity and teaching workflow. Keep security and repository constraints, but replace contradictory implementation, execution-checklist, and ordinary goal instructions. Ensure both prompt-building paths agree.
3. **Capability exposure:** return a mode-filtered tool catalog and schemas. Use explicit reviewed capabilities, not a blanket `not mutating` test. Initially permit only repository inspection and bounded documentation retrieval. Block general shell, verification executors, source writes, generic HTTP actions, unreviewed MCP, and delegation.
4. **Execution enforcement:** check authoritative session policy at each invocation, including stale or manually specified tool calls. Do not pass an optional caller-supplied boolean that defaults to permissive. Apply restrictions to native command execution paths and lifecycle hooks as well. Security approval remains a separate, additional requirement.
5. **Output handling:** buffer a candidate response, validate its teaching structure and prohibited implementation content, and expose only accepted content. Cover prose, inline snippets, diffs, tool argument previews, tool results, summaries, remote events, and observer fan-out. Exact existing-code excerpts require provenance. Permit bounded regeneration on rejection and return a useful failure message if repair fails.
6. **Turn completion:** a question or learner action is a valid end of turn. `awaiting_learner` prevents forced execution, goal continuation, “implement plan” handoffs, and compaction recovery from taking over. Resume on real learner input, not an automatic implementation prompt.
7. **Persistence:** restore the policy before exposing tools, executing hooks, or starting restored activity. Preserve structured learning state across compaction; do not reconstruct permissions from a model-written summary.

Runtime tool blocking can enforce which iTE-controlled actions are permitted. Semantic “never reveal a solution” checks remain imperfect with arbitrary language models: code can appear inline, and a solution can be written in prose. Do not advertise a mathematical guarantee that no model can ever disclose code. The enforceable promise and the evaluated conversational promise must be documented separately.

Test execution is a later extension. Tests run arbitrary project code; command-name allowlists and existing mutation labels do not isolate side effects. A future `/learn check` needs a deliberately restricted runner, a disposable workspace, controlled network and writes, and explicit reporting of generated artifacts. Run only against the learner's attempt. Never quietly fall back to an unrestricted shell.

## Interaction with existing features

- **Plan mode:** v1 should make learning and plan mode mutually exclusive. On entry, retain saved plans but deactivate plan execution. Do not automatically reactivate plan mode on exit. Learning can discuss a plan without invoking its implementation handoff.
- **Goals:** retain ordinary goal data, but exclude it from active execution prompts and continuation while learning. Keep paused work visibly suspended on exit; no surprise resumption. Defer dedicated educational goal scheduling.
- **Skills and subagents:** keep project knowledge where useful, suppress incompatible write instructions, and block skill-invoked execution. Disable child agents in v1. Later delegation must inherit the same or narrower policy at every level and validate returned output.
- **Hooks:** no arbitrary hook commands during strict learning. Typed internal persistence is separate. Expose that hooks are suspended so configured automation does not fail mysteriously.
- **Reup:** show a compact `Learn · waiting for your attempt` status near the composer. Use the existing conversation surface for the objective, next step, and documentation. Follow DESIGN.md: no heavy new dashboard, streak system, or mandatory quiz modal.
- **Remote:** enforce on the host before broadcasting any content; restore and report state over the protocol. If remote editing is unavailable, review pasted attempts and logs without pretending access exists.
- **Approval/yolo:** cannot widen learning capabilities. `/learn off` changes the learning policy but still respects normal sandbox and approval constraints.
- **Failure/restart:** an incomplete restore must not silently become a writing agent. Reapply persisted restrictions or stop the turn with an explicit error.

## Staged implementation

### Stage 1: enforce the commitment

Implement session state, shared command transitions, mode-aware prompts, a small inspection capability set, invocation enforcement, hook/delegation restrictions, learner handoff semantics, buffered response validation, persistence, and visible local/remote status. Keep code and execution with the learner. Ship as an experimental feature with clear conversational limits.

Primary files: `commands/learn.py` (new), `commands/__init__.py`, `agent/session.py`, `agent/session_manager.py`, `agent/agent.py`, `tools/policy.py`, `tools/registry.py`, `prompts/system.py`, `context/manager.py`, `hooks/hook_system.py`, Reup turn/status handlers, remote command/protocol state, and all snapshot restoration paths.

### Stage 2: make it teach well

Add `learn.md` loading and explicit initialization, attempt/diff review, progressive hints, documentation version matching, inspectable evidence notes, and occasional independent transfer checks. A lightweight profile may be included in stage 1 if it does not displace enforcement work.

### Stage 3: extensions justified by pilot results

Consider isolated checks, optional unrelated worked examples in a separately named profile, opt-in cross-session learning memory, and narrower read-only delegation. Avoid curriculum generators, automatic proficiency grades, keystroke surveillance, and arbitrary command execution until they have a demonstrated need.

Do not estimate calendar delivery before auditing the mode transition, output validation, and restore paths. These are the largest engineering uncertainties, rather than the slash command itself.

## Validation and decision criteria

Deterministic tests should cover:

- Blocked writes through direct tools, structured writers, shell, verifier overrides, MCP, hooks, skills, child agents, and native execution commands.
- Model schemas exclude forbidden tools, and invocation rejects stale or hallucinated calls regardless of approval setting.
- Activation during a turn waits for quiescence; sibling sessions keep their own policy; queued actions and remote races cannot reuse an old policy epoch.
- Save/resume/fork/compaction retain strict mode and `awaiting_learner`; legacy snapshots default safely to ordinary mode only when no learning state was saved.
- Learner handoff ends cleanly without execution todos, goal continuation, or hidden plan handoff. Exit does not silently resume suspended work.
- Rejected code does not reach text deltas, observers, remote broadcasts, tool-card previews, or session summaries before validation.
- Missing, oversized, unreadable, adversarial, and out-of-scope profiles retain the runtime boundary and report their status.

Separate model-behavior evaluations across supported providers should challenge inline code, patches, pseudocode, verbal solutions, raw tool output, documentation prompt injection, frustration, “just do it,” and requests to evade mode. Measure useful assistance as well as leakage and false positives. A validator that blocks every answer passes no meaningful teaching test.

For the product pilot, compare ordinary iTE, prompt-only teaching, and enforced learning mode on matched tasks. Measure unaided debugging and a changed-case implementation after assistance is removed, ideally again after a delay. Also observe frustration, help usefulness, abandonment, mode exits, and implementation completion. Do not use generated lines, number of quizzes, or immediate task speed as the primary success measure.

Proceed beyond the pilot if learners find it useful, retain ownership, and show promising independent transfer without intolerable frustration. If the pilot only makes implementation slower, improves explanation fluency without transfer, or regularly needs takeover, revise the teaching workflow before expanding the feature.

## Immediate next engineering slice

Build one end-to-end path: `/learn on` → explain a small task → learner edits externally → `/learn review` → discuss a defect → wait. Exercise it through both Reup and the headless runtime, with save/resume and an attempted write bypass. This tests the core promise before adding a broad learning platform.

This investigation changes no runtime behavior and does not create an active workspace `learn.md`.
