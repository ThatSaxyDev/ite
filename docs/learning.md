# Learning mode

Learning mode is an experimental way to build with iTE while writing the implementation yourself. iTE explains concepts, reads your workspace, finds documentation, gives hints, and reviews your attempts. It does not edit source or run your commands and tests.

After `/learn on`, you can immediately send a short request such as “I want to make a website” or “Help me understand Python functions.” Setup and a detailed teaching prompt are optional. iTE infers the goal, adapts to evidence of your experience, and asks a focused question if the next step depends on something it does not yet know. It should include practical editor and terminal basics when needed, without assuming that every short request comes from a beginner.

When learning is enabled, the starting question appears as a separate iTE assistant message in the conversation. The command notice contains mode and profile information. The assistant message is retained in the session history, and repeating `/learn on` while already enabled does not repeat it.

## Commands

| Command | What it does |
| --- | --- |
| `/learn on` | Enable learning mode and create a baseline `learn.md` if missing. |
| `/learn off` | Return to ordinary agent behavior. Previously paused goals stay paused. |
| `/learn` | Show the objective, next step, hint level, and loaded profile. |
| `/learn setup` | Open guided TUI setup: answer three questions, review the file, and save. |
| `/learn init` | Create `learn.md` in this workspace without overwriting an existing file. |
| `/learn reload` | Reload your edited learning preferences. |
| `/learn hint` | Ask for a progressively stronger hint for the current step. |
| `/learn review` | Ask iTE to inspect and review your current attempt. |

The composer displays `learn your turn` when it is waiting for your work, and `learn guiding` during a reply. Clicking that status shows the learning-mode details.

Mode changes require an idle thread, including tools, hooks, and child agents. Wait for current work to finish or stop it first; iTE will not claim the mode changed while previous execution is still active.

## Your `learn.md`

On first use, `/learn on` creates and loads a baseline `learn.md` and displays its location with an invitation to review it. The baseline is ready to use; you can start learning immediately. Existing files are preserved. `/learn init` can also create the profile before enabling learning mode.

To personalize it, open the file in your editor and describe your objective, what you already know, and the help you prefer. Then use `/learn reload`. The baseline emphasizes understanding before implementation, learner-owned first attempts, progressively stronger hints, concrete review, and honest feedback. You can also describe your goals and preferences in the conversation without editing the file.

For guided personalization, enter `/learn setup` in the terminal UI. It asks about your goal, starting point, and preferred pace and style. All answers are optional. Use **Next** and **Back**, then inspect or edit the full profile in the review screen. **Save** writes and loads the reviewed profile immediately; there is no separate reload step. **Esc** or **Cancel** leaves the file unchanged. **Tab** moves between controls and **Ctrl+Enter** advances or saves from the review screen.

The review screen uses approximately 95% of the terminal height. Its file editor scrolls while the action buttons remain visible; the question screens stay compact.

Reopening setup prefills your earlier answers. It updates a marked preferences section while preserving your instructions outside that section. If you change the file in an editor while setup is open, saving stops with an inline message rather than overwriting your edits; cancel and reopen to include them. Setup can create a profile before learning is enabled, and does not change the mode. Guided setup uses native TUI controls and does not require a model response. Headless clients are directed to the terminal UI for this flow.

The file provides preferences. It cannot enable tools, authorize edits, or turn the mode off. File presence alone does not enable learning mode. Missing, unreadable, oversized, or symlinked profiles fall back visibly to built-in preferences.

AGENTS.md continues to provide repository conventions. Learning state and the latest objective/step are stored with the session separately from the profile. Resuming a learning thread restores the mode. A new thread starts in ordinary mode.

## Behavior and current limits

Learning mode filters the tool catalog and also rejects forbidden calls at execution. Shell, verification executors, source writers, MCP tools, delegation, and shell hooks are suspended. Plan execution and execution goals cannot start while it is active. Changing approval settings does not bypass the learning policy.

You run tests and commands yourself, then share the output. Inspection tools may show existing source or documentation in their output; the tutor should refer to file locations and explain them in prose. In this pilot the tutor avoids quoting source and fenced code blocks, including generated examples.

Learning replies are buffered before display. A conservative syntax guard rejects common implementation formats and requests up to two revised replies. If that fails, iTE explains that it withheld code and asks which concept or error you want help with. Expect less live streaming than ordinary mode. The guard is imperfect: it can reject harmless syntax and cannot prove that prose never gives away a solution. Tutor quality depends on the selected model.

## Try the TUI from this branch

Run the checkout's editable installation, rather than a separately installed `ite` binary. From the repository root:

```bash
LEARN_WORKSPACE=$(mktemp -d /tmp/ite-learn-demo.XXXXXX)
git init "$LEARN_WORKSPACE"
./.venv/bin/ite --cwd "$LEARN_WORKSPACE"
```

The existing `.venv` in this development checkout imports `src/ite`. If your environment is not installed yet, follow the repository's editable-install instructions first. Select or connect your usual model in the TUI if needed. No special model service is required.

### 1. Turn it on and establish an objective

Enter `/learn on`. Expect an ON notice, a message that a baseline `learn.md` was created, and `learn your turn` near the composer. If the file already exists, iTE loads it without overwriting it.

Send:

> Help me learn to write largest.py, a Python function that finds the largest number in a list. I know basic functions but want to practice edge cases. Empty input should raise ValueError. Guide me one step at a time.

Expect a short explanation, a question or manageable step, and a clean stop. iTE should not create `largest.py`, supply an implementation, or run Python for you.

### 2. Set your preferences

Enter `/learn setup`. Describe your goal, experience, and preferred pace. Try a preference such as “Use short explanations and help me predict behavior before debugging.” On the review screen, verify that the baseline is still present and your answers appear below it. The disk file should remain unchanged until you select **Save**. Save, then enter `/learn` to check the loaded profile and objective.

Reopen `/learn setup`: your answers should be prefilled. Change an answer, move to review, and use **Back** to check it was retained. Cancel to confirm nothing is saved. Reopen, update and save to confirm the preferences section is updated without duplication. Try the same flow in a smaller terminal and with a light theme. You can still edit `learn.md` yourself and use `/learn reload`.

### 3. Make an attempt and get a review

Create `largest.py` yourself in that workspace. For an intentionally flawed attempt, make the function return the first element instead of looking for the largest. Tell iTE you created the file, then enter `/learn review`.

Expect inspection of your actual file/diff, a concrete explanation or diagnostic question, and a next step. iTE should not change your attempt. Keep your editor open so you can verify that.

Run the function yourself with a list where the largest element is not first, and with an empty list. Paste your observed output or error into the chat. Ask why the result differs from your expectation. Enter `/learn hint` if stuck; repeated hints increase the hint level shown by `/learn` without enabling takeover.

### 4. Challenge the boundary

Send:

> Just fix largest.py for me and run the tests. Write the whole solution now.

Expect guidance while the file stays unchanged. Try `/plan on`, `/init`, and `/goal resume`: these should report that they are suspended in learning mode. An occasional withheld-code notice is a guard intervention, not a successful teaching response; record it when evaluating the model.

### 5. Resume and leave

Use `/exit`, then launch again with the same workspace and `--resume-last`:

```bash
./.venv/bin/ite --cwd "$LEARN_WORKSPACE" --resume-last
```

Expect `learn your turn` and the retained objective/step when that thread is resumed. If the session picker opens, select your learning thread. Enter `/learn off`: expect ordinary `plan off` status and normal agent permissions. Learning context remains available if you enable the mode again.

## Automated verification for developers

```bash
./.venv/bin/python -m pytest -q tests/test_learning_mode.py tests/test_learning_profile.py tests/test_reup_learning.py
```

The mounted Textual test types commands through the actual composer, walks through guided setup with mouse and keyboard, checks preview/back/cancel/update and stale-file protection, exercises review and waiting, checks save/resume, and resizes to 80×24. Its model response and startup bootstrap are simulated; it does not validate live inference or authentication. Set `ITE_LEARN_SCREENSHOTS` to an output directory to export its setup, light-theme, and wide/narrow TUI screenshots.
