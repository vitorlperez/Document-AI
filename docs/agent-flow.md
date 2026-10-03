# Document agent flow

Questions over a selection (`scope=selection` with `AGENT_TOOLS_ENABLED=true`) run through one flow in
`backend/app/knowledge/agent.py` (`AgentService.ask`). There is no feature flag and no keyword-routed
path: the stages below are the only way an answer is produced.

| Stage | Method | Input → output |
| --- | --- | --- |
| 1. Classify | `AgentService.classify` | message + `ConversationState` (files listed in the last answer, files attached in the previous turn, previous answer) → `IntentDecision` (closed schema in `intent.py`: intent, target, ordinals, tool, query) |
| 2. Execute tools | `AgentService.execute` → one handler per intent in `_handlers` | decision + `AgentRequest` (authorized scope, providers, mentions) → `AgentRun` with the `ToolResult`s it read |
| Security fence | `knowledge/untrusted.py` + `presentation.py` | nonce around untrusted sources, invisible-control cleanup, read-only tools and service output-link guard; see [RAG threat model](seguranca/prompt-injection-rag.md) |
| 3. Synthesize | `AgentService._synthesize` | tool outputs (sources without URLs, catalog names) → one grounded, cited answer, or `None` when it cannot be verified |
| 4. Cite | `AgentService.cite` | `AgentRun` → final `QuestionResult` whose `citations` always list the documents used, with their links |

Targets are resolved from structure, never from wording: the request's `@` mentions first, then
ordinals or "all of them" over the files listed in the previous answer, then the previous turn's files.
Files reused from a folder listing are re-authorized against the current catalog and must still be in
that folder. Model output never carries scope: tenant, providers and file ids always come from the request.

## Fallbacks

- Classifier error, timeout (`AGENT_INTENT_TIMEOUT_SECONDS`) or output outside the schema →
  `fallback_intent`: a relevance search over what the user attached (`decided_by: "fallback"`).
- A decided intent the targets cannot serve (e.g. a listing without a folder) → the same relevance search
  (`fallback: "plan_rejected"` in `resolved_context`).
- Synthesis error, timeout, uncited or out-of-range markers → the extractive listing, the per-file
  batched summary, or the evaluated document summary, all of them cited.
- No evidence → an honest answer that names the consulted files, which are also the Fontes. The agent
  never returns `answer=None`.
- Agent deadline (`AGENT_MAX_SECONDS`) or provider outage during retrieval → `AIProviderUnavailable`,
  which the API reports as a retryable 503 with a sanitized diagnostic.

A `conversation` intent runs no tool; when the conversation is about files (attached in the previous turn
or listed in the last answer), those files, re-read from the current catalog, stay as its Fontes.

## Inventory follow-ups

An unmentioned library listing reads the authorized local file catalog instead of semantic top-k.
`inventory_stats` counts catalog file identities, including files without indexed content; it does not
count citations, chunks or unique names. `select_files_by_topic` assesses each readable candidate in
batches of ten and returns only matches with a supporting quote verified against that file's text.
The LLM and Jev classifiers both recognize these intents. Current mentions still override history.

Counts and thematic selections revalidate historical references, their original inventory folders,
providers, memberships and current document admission. Statistics carry all candidate references into
the next turn; selection carries only the matching files. Names shared by different files remain
separate identities, and previous file ordering is preserved.

The inventory is bounded by 500 files and the configured tool-result byte budget. Its exact catalog
total, returned count and partial-list flag are separate. Follow-ups on a partial list count that
selection and retain the partial-list warning; they do not silently widen to the library or reuse a
stale total as today's full Drive count. Theme analysis shares the existing file-summary timeout
budget, visits candidates beyond the global 24-source synthesis cap, and reports unreadable,
title-only, failed, invalid or timed-out assessments as unknown. It uses the existing bounded snapshots
(up to six leading chunks / 6,000 characters), so thematic completeness over entire files is not
guaranteed. Quote validation proves provenance, not semantic entailment; live-model evaluation and
independent review remain separate checks.

Folder counts cover only files directly in the selected folders and say so explicitly; subfolders
are not traversed. This scope persists across statistics follow-ups, including empty and multiple
folder selections, and is reset by an explicit library query. Snapshots bound chunk rows per
document in SQL with a window function (PostgreSQL and SQLite), and bound the text of each row
before returning it. Topic quotes require 20–600 normalized characters and at least three words
of two or more letters. Unicode, case and whitespace normalization checks file-local provenance;
it does not establish semantic entailment. Counts without assessed themes omit content citations
through the final citation stage while retaining catalog references for subsequent turns.

## Moving to LangChain / LangGraph

The stages already have the shape of a graph, so a later migration does not need a redesign. Each stage
becomes a node over a typed state that mirrors `AgentRun` (request, conversation state, decision, tool
results, answer): `classify` is the entry node, each entry of `_handlers` becomes a conditional edge from
it to a tool node, `_synthesize` is a node with a verification edge back to the extractive fallback, and
`cite` is the terminal node. The local tools of `LibraryToolExecutor` map one-to-one to LangChain tools
whose arguments stay narrow (never scope), the closed `INTENT_SCHEMA` becomes the structured output of the
router model, and the deadline and byte limits become graph-level limits. What must not change in the
move: scope comes only from `AgentRequest`, every answer passes through `cite`, and a failed model call
takes the same fallback edges listed above.
