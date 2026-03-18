# Reup modal click fix

## Symptom

A newly opened modal renders correctly, but its buttons do not respond to mouse clicks.

This showed up in the change review panel when opening `ConfirmModal` from:

- `#change-review-discard-file`
- `#change-review-discard-all`

The same modal still worked from keyboard bindings, and older reup modals like session / branch / attach were clickable.

## Root cause

Do not open a modal directly from a raw `events.Click` handler on a custom widget and then await it inline.

That launch path can leave the modal in a bad pointer-routing state in reup, even though the modal layout and `Button.Pressed` handlers are correct.

## Working pattern

From the click handler:

1. `event.stop()`
2. hand off to `self.run_worker(...)`
3. open the modal inside that worker coroutine

Example:

```python
async def _run_change_review_discard_file(self) -> None:
    confirmed = await self._confirm_change_review_discard(
        title="Discard file changes?",
        body=f"Discard all staged and unstaged changes for `{rel_path}`?",
    )
    if not confirmed:
        return

@on(events.Click, "#change-review-discard-file")
def on_change_review_discard_file(self, event: events.Click) -> None:
    event.stop()
    self.run_worker(self._run_change_review_discard_file(), exclusive=False)
```

## Rule of thumb

For reup:

- `Button` inside modal: fine
- `Button.Pressed` inside modal: fine
- opening modal from normal async flow: fine
- opening modal directly from raw `events.Click` on a custom `Static` / panel chip: risky

If a modal is launched from a custom click target, prefer `run_worker(...)` as the handoff boundary before calling `_open_modal(...)`.
