# Implementation Spec: Phase 2 — Knowledge-Base Extension

**Status:** In progress
**Date:** 2026-06-17

## What this phase does
Extend the existing KB entity-observation model with new observation types:
- `prompt_response` — prompt/response summaries
- `tool_call` — tool invocations and their results
- `session_context` — repo path, git branch, files touched, commands run

Redaction pass strips secrets before any write. Capture only — no summarization, retrieval, or training logic.

## Design decisions

### Schema: additive column on `observations`, no new table
Adding an `observation_type TEXT DEFAULT 'general'` column to the existing `observations` table.
- No new table: avoids schema fragmentation and keeps existing queries working unchanged
- `DEFAULT 'general'` means all 574 existing rows are backward-compatible without a data migration
- The structured context fields (repo_path, git_branch, files_touched, commands_run) are serialized into the existing `content` TEXT column in a tagged text format readable by the existing `search` path

### Content format for new types
```
[TYPE] TITLE
  repo: path/to/repo @ branch-name
  files: file1, file2
  commands: cmd1, cmd2
  NARRATIVE/SUMMARY
```
This keeps the content human-readable and compatible with the existing LIKE-based search without requiring a JOIN or new index.

### New endpoint: POST /capture
Accepts structured input, runs redaction, writes via existing `addObservation`. Does not bypass the existing mutation tracker or snapshot logic.

### Redaction
Applied to all text fields before serialization. Patterns:
- `sk-...`, `pk-...`, Bearer tokens
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and any `*_KEY`, `*_TOKEN`, `*_SECRET` env var patterns
- `.env` file values (KEY=VALUE lines)
- SSH private key blocks (`-----BEGIN ... PRIVATE KEY-----`)
- Passwords in connection strings (`postgres://user:PASSWORD@...`)

Replacement: `[REDACTED]`

## Files changed
- `knowledge-base/src/db.ts` — ALTER TABLE to add `observation_type` column
- `knowledge-base/src/redact.ts` — NEW: redaction module
- `knowledge-base/src/graph.ts` — add `captureEvent()` function
- `knowledge-base/src/rest-api.ts` — add `POST /capture` route
- `knowledge-base/src/mcp-server.ts` — add `capture_event` tool
- `knowledge-base/src/sdk.ts` — re-export `captureEvent`

## Acceptance criteria
1. `POST /capture` with a prompt_response payload writes a redacted observation to KB
2. `observation_type` column exists and is populated on new writes
3. All 574 existing observations still readable via `/graph` with `observation_type = 'general'`
4. A payload containing a real API key pattern gets that value replaced with `[REDACTED]` before write — verified by reading back the stored observation
