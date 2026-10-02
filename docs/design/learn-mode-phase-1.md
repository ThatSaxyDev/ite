# Learning mode — first implementation phase

Scope: a usable strict pilot on `feat/ite_learn`.

1. Add session-owned learning state, profile loading, explicit commands, and snapshot restoration.
2. Enforce an inspection-only tool catalog and invocation policy, suspend shell hooks and delegation, and reject mode changes during active work.
3. Replace implementing prompts with a tutor workflow, suppress live reply streaming until syntax validation, and end turns while awaiting the learner.
4. Integrate commands and visible status in Reup and the headless runtime; disable plan/goal continuation in learning mode.
5. Verify boundaries, persistence, provider output handling, and actual Textual interactions. Document an interactive manual test.

Deferred: isolated command/test execution, cross-session proficiency tracking, and semantic guarantees about solution leakage. The syntax guard is conservative and cannot prove that prose never gives away a solution.

## Completed verification

All five steps are implemented. The selected regression suite passes 148 tests plus 17 subtests. It includes a mounted Reup test that enters commands through the composer, walks through guided setup, editable preview, back/cancel, repeated updates and stale-file protection, reviews an unchanged learner file, checks the waiting status, restores a saved learning session, switches off, and resizes to 80×24 and 110×50. The review screen uses 95% of available terminal height, with persistent action buttons. Guided setup uses native modal controls following DESIGN.md and the [Textual screens guide](https://textual.textualize.io/guide/screens/). Model inference and startup authentication are simulated in that test; real-provider teaching behavior still needs the manual walkthrough in [learning.md](../learning.md).

The new source modules pass Ruff and focused mypy checks. Both the source distribution and wheel build successfully. Broader repository checks still have existing failures reproduced on the branch's original HEAD, including continuation recovery, UI onboarding/badge tests, and subagent bookkeeping; they are outside this phase.

Live assistant pacing is implemented alongside this phase; see [assistant-typing.md](assistant-typing.md) for its lifecycle and a normal-chat testing walkthrough.
