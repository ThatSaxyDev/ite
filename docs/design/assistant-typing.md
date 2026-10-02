# Assistant typing in Reup

Live assistant replies use a display clock independent of the provider's chunk boundaries. Incoming text is accepted immediately and queued on its Markdown widget. The renderer reveals small fragments at roughly 10 ms intervals, waits without polling when no text is available, and resumes when another chunk arrives.

Short replies reveal one character at a time. Large backlogs reveal larger fragments to catch up; completion accelerates long queues. This intentionally adds some display latency. Repaints may combine characters when a terminal or Markdown renderer cannot keep up.

The buffer is local to each widget. Completion drains it before final Markdown reconciliation and before the next assistant segment. A corrected authoritative final response cancels obsolete queued text before updating the widget. Interruption preserves received text immediately without continuing a slow animation. Widget removal cancels its clock, including while completion is awaiting it; this does not cancel a background agent turn.

The learning-mode introduction uses the same mechanism. Learning replies remain fully validated before entering the display buffer. Saved history, command notices, tool output, and setup previews are not animated by this path. The network protocol and provider chunking are unchanged; this change controls the local terminal feed.

## Manual test

Start the checkout with `./.venv/bin/ite` and your usual model.

1. Use `/learn off` and ask: “Explain Python variables and loops with short examples in chat.” Expect a paced live reply and intact code formatting.
2. Try a longer explanation. Expect faster catch-up when there is a backlog and a complete final reply.
3. Stop a long reply while text is appearing. Expect the animation to stop and the received text to remain, with no later fragments leaking into the next reply.
4. Start another reply. Switch threads during it, then return. The active thread should not receive text from the outgoing thread's display clock.
5. Use `/learn on`; the introduction types using the same renderer. Send a short learning request and try `/learn hint` or `/learn review`. These replies animate after validation.
6. Exit and resume. Existing history should appear immediately.

Automated checks: `./.venv/bin/python -m pytest -q tests/test_assistant_typing.py tests/test_reup_learning.py`. These use deterministic text bursts and simulated provider responses, with mounted Textual widgets and a mounted Reup composer flow.
