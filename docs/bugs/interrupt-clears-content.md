# Bug: Interrupt/Cancel Clears Completed Work and Triggers Unwanted Re-runs

## Summary
When a user cancels/interrupts an agent turn (e.g., with Ctrl+C or a cancel action), the UI clears all the work that was already completed and may trigger automatic re-runs or recovery logic.

## Root Cause Location
File: `src/ite/ui/reup/app.py`

### Key Code Sections

#### 1. Turn Completion Logic (lines ~4600-4652)
```python
# After turn completes...
if completed_normally and self._active_session_id() == session_id:
    await self._dispatch_queued_payload_if_ready()  # Triggers new turn!
elif (
    self._active_session_id() == session_id
    and run_state.failure_recovery_payload is not None
):
    await self._clear_inflight_turn_ui()
    await self._dispatch_queued_payload_if_ready()  # Triggers new turn!
elif self._active_session_id() == session_id:
    await self._clear_inflight_turn_ui()  # Clears work!
    self._restore_queued_payload_after_unsuccessful_turn()  # Restores to composer
```

#### 2. CancelledError Handler (lines ~4621-4629)
```python
except asyncio.CancelledError:
    if self._active_session_id() == session_id:
        self.post_notice("Interrupted", "Stopped current run.")
        run_state.active_turn_task = None
        run_state.is_turn_running = False
        run_state.context_meter_floor_pct = None
        self.refresh_header()
        self._set_loading_state("idle", busy=False)
        await self.auto_save()
    # Missing: Should NOT proceed to the cleanup logic at lines 4642-4652
```

#### 3. Auto-Resume Logic (lines ~3718-3737)
```python
async def _dispatch_queued_payload_if_ready(self) -> None:
    # Checks for auto_resume_payload, failure_recovery_payload, _queued_turn_payload
    # If any exist, starts a NEW agent turn automatically
```

## The Problem Flow

1. User sends a message → `_dispatch_payload()` starts agent turn
2. Agent streams response, user sees content appearing
3. User interrupts/cancels → `CancelledError` raised
4. `CancelledError` handler runs but does NOT prevent the cleanup logic
5. Execution falls through to lines 4642-4652
6. `_clear_inflight_turn_ui()` removes the streaming widget (content lost!)
7. `_restore_queued_payload_after_unsuccessful_turn()` restores draft to composer
8. OR `_dispatch_queued_payload_if_ready()` starts a NEW turn (re-run loop!)

## Expected Behavior

On interrupt/cancel:
- Preserve the partial/completed response that was already streamed
- Do NOT trigger any auto-resume, recovery, or re-run logic
- Do NOT restore the message to composer (it was already sent)
- Simply stop and show what was completed

## Proposed Fix

The `CancelledError` handler needs to either:
1. Return early to skip the cleanup logic at lines 4642-4652, OR
2. Set a flag that the cleanup logic checks to skip auto-resume/restore

### Option 1: Early Return (Simpler)
```python
except asyncio.CancelledError:
    if self._active_session_id() == session_id:
        self.post_notice("Interrupted", "Stopped current run.")
        run_state.active_turn_task = None
        run_state.is_turn_running = False
        run_state.context_meter_floor_pct = None
        self.refresh_header()
        self._set_loading_state("idle", busy=False)
        await self.auto_save()
    # ADD: return here to skip the problematic cleanup logic
    return
```

### Option 2: Flag-Based Check
Add a flag like `run_state.was_cancelled = True` in the CancelledError handler, then check it before calling `_clear_inflight_turn_ui()` and auto-resume logic.

## Related Code

- `_clear_inflight_turn_ui()` at line 5297 - removes streaming widget
- `_dispatch_queued_payload_if_ready()` at line 3718 - triggers new turns
- `_restore_queued_payload_after_unsuccessful_turn()` at line 3739 - restores draft

## Testing Notes

To reproduce:
1. Start a long-running agent turn
2. Let some content stream to the UI
3. Press cancel/interrupt
4. Observe: content disappears and/or new turn starts automatically

## Priority

High - This causes data loss (cleared content) and poor UX (unwanted re-runs).
