# Context compaction lifecycle

Reviewed September 30, 2026. This document records the audit findings, the implemented contract, and the remaining limits.

## Audit findings

The original infrastructure remained in place, but several integration gaps threatened long-running tasks:

| Finding | Impact | Resolution |
| --- | --- | --- |
| The summarizer skipped all system messages, including prior compaction artifacts | Second and later compactions could lose the original objective and decisions | Carry prior artifacts into every summarization pass |
| Automatic compaction returned from the agent loop and requested a UI restart | Continuation depended on the surface; a new run reset recovery and iteration state | Resume in the same agent loop; boundary events no longer request another UI turn |
| Eight-message minimum and a fixed 12,000-token reserve | Large single messages and small context windows could never trigger | Allow any nonempty history and scale the reserve for smaller windows |
| Tool schemas were absent from token estimates | Requests could overflow earlier than expected | Include current registry schemas and calibrate estimates against observed prompt usage |
| Fixed per-message truncation plus unbounded aggregate summary input | User constraints could disappear before summarization; recovery requests could themselves overflow | Process user/assistant text and tool arguments in bounded chronological passes; preserve both ends of long tool outputs |
| Ten preserved messages had no token budget | A large recent output could immediately refill the next window | Fit the tail below the continuation budget while retaining valid tool exchanges |
| Summary success required usage metadata | Compatible providers without telemetry were treated as failures | Treat usage as optional accounting; require completed nonempty output |
| Automatic summary failure silently proceeded to inference | Repeated oversized requests and unclear failure state | Stop with a specific error, leaving the conversation active |
| Snapshot message fallback omitted the artifact | Restoring without full transcript state could lose the summary | Save inline compact artifacts, exempt them from snapshot text truncation, and restore boundary counters/timestamps |
| Pruning overwrote raw tool output; interruption cleanup rebuilt only active history | Earlier transcript evidence could be destroyed | Prune the prompt view while retaining raw output; append repaired active views without erasing earlier events |

## External reference behavior

These are product-specific implementations, not a formal universal standard.

- **Codex:** exposes an automatic compaction token threshold, with model defaults when unset. Current configuration also supports counting either total active context or growth after the carried prefix. See the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
- **OpenAI Responses:** offers both server-managed and standalone compaction. The returned window can contain retained items plus opaque state; standalone output must be forwarded intact, and the input must still fit the model window. This is distinct from a provider-neutral textual summary. See [Compaction](https://developers.openai.com/api/docs/guides/compaction).
- **Claude Code:** clears older tool outputs before summarizing, supports manual compaction focus, and stops repeated compaction when oversized content causes thrashing. See [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works#when-context-fills-up).
- **Claude Code continuity:** reloads persistent rules, memory, plans, and invoked skills under documented limits. Running background work remains active and is surfaced again after compaction. See [What survives compaction](https://code.claude.com/docs/en/context-window#what-survives-compaction).

The resulting iTE contract is: trigger before overflow, preserve task state, regenerate authoritative runtime instructions, retain protocol-valid recent exchanges, commit only successful summaries, continue without another user turn, and bound unsuccessful recovery.

## Implemented lifecycle

1. Before inference, try pruning older tool results from the active prompt. Protection, pruning minimums, and the early pruning buffer scale down for small windows. Original results remain in exported transcript state.
2. Estimate the complete prompt, including dynamic tool schemas. Observed provider prompt usage supplies a conservative scaling factor when the local tokenizer undercounts.
3. Trigger at the lesser of 85% of the configured window and the window minus the reserve. The reserve is the lesser of 12,000 tokens and 20% of the window. Any nonempty history is eligible.
4. Summarize active history together with its previous compact artifact and current goal, session memory, plan, todos, and running subagent identifiers. Base instructions and durable memory regenerate independently on normal inference requests.
5. Limit each summary request using a 70% input budget, reserving a summary budget of up to 8,192 local tokens or 20% of the calibrated window. Oversized history is processed chronologically with the preceding summary carried into the next pass. At most 32 passes are allowed. Non-text attachments become explicit references rather than base64 text.
6. Reject empty, unfinished, filtered, or oversized summary output. Provider errors and missing completion events also fail. Token usage is accumulated where supplied; it is not a success prerequisite.
7. Fit the summary, regenerated instructions, schemas, and a valid recent tail under 70% of the window, leaving a gap below the trigger. If fixed context alone cannot fit, fail before changing the active history. Save the artifact before committing the boundary. Manual and automatic paths use `Session.compact_context`.
8. Emit the boundary and continue inference inside the current agent loop. Overflow recovery retries once for the failing request; two transient post-compaction retries are allowed. Failed attempts do not consume the final available loop iteration. Three consecutive automatic compactions that immediately refill context are allowed before a clear stop.
9. Session snapshots retain both inline summaries and full transcript state. Restore reconstructs compaction counters and timestamps and keeps pruned output excluded from active prompts.

Summaries explicitly preserve the objective, corrections, completed work, remaining work, evidence, exact identifiers, blockers, and the scope of user authorization. They do not create permissions. Runtime state is re-injected separately so plans, todo IDs, and queued/running subagent runs do not depend solely on summary quality.

## Verification and limits

Regression coverage includes repeated compaction, long history across multiple passes, missing telemetry, incomplete output, multimodal tool results, bounded tool tails, snapshot fallback, raw transcript retention, provider token calibration, disk failure, failed automatic compaction, overflow retry at the last iteration, repeated overflow, and UI boundary handling.

`/setup` discovers context windows for listed Ollama models through metadata-only requests. Cloud models use model metadata from `/api/show`, with a public Ollama metadata fallback when the local server cannot resolve the cloud model. Local models use `/api/ps` allocation or explicit `num_ctx` parameters, capped by the model maximum; a published maximum alone does not establish a local server's effective limit. Detected values are shown in a disabled field and saved with `context_window_source = "ollama_model_api"`. Selecting Other or an unavailable effective limit allows manual entry, saved as `user_configured`. Other OpenAI-compatible providers also require a positive integer. These limits reach the active session, context meter, and compaction threshold. OpenRouter continues to use its model metadata. Entering a local Ollama limit does not configure the server.

Token counts remain estimates across third-party tokenizers, especially for images and provider-specific serialization. Actual context window configuration must match the selected model. Summary fidelity still depends on the provider model; deterministic tests establish lifecycle behavior, not semantic retention quality on real workloads. A live long-task evaluation across the supported providers remains useful.

Provider-native Responses compaction, user-supplied `/compact` focus instructions, dedicated pre/post-compaction hooks, and automatic file rereads are separate extensions. This implementation retains the existing Chat Completions-compatible provider path and does not assume opaque Responses state is portable across providers.

### Validation results

- Context, memory lifecycle, snapshot, and memory manager suite: **86 passed**. One existing response-intent assertion was excluded after reproducing its failure against the unchanged HEAD source.
- Focused compaction UI and integration checks: **7 passed**, including confirmation that an internally resumed boundary does not enqueue another turn.
- Remote protocol, tool recovery, session naming, and subagent checks: **50 passed**; the two subagent failures also reproduce on unchanged HEAD.
- Broader continuation checks exposed four existing incomplete-response failures. An exploratory UI suite exposed unrelated fixture/behavior failures and was interrupted after stalling. These results do not establish that the full repository suite is green.
- Comparing Ruff diagnostics for eight touched source modules against unchanged HEAD found **no new diagnostics**; 38 existing diagnostics remain in that scope. The rewritten compactor and its regression test module pass Ruff. Python compilation and `git diff --check` pass.
