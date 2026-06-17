---
name: personal-ai-memory-gateway
description: Domain knowledge for Rihan's Personal AI Memory Gateway — the unified architecture connecting Headroom (proxy/compression), Claude Mem, and the existing knowledge-base MCP server into one retrieval authority with redundant fallback storage. Use this skill whenever working on Headroom configuration, Claude Mem ingestion, the knowledge-base MCP server, LaunchAgent setup for AI tooling on this machine, session-resume capsules, or any phase (0 through 6) of this project. Also trigger on mentions of: Headroom, Claude Mem, knowledge-base MCP server, memory bridge, fallback retrieval, degraded flag, entity-observation model, or `~/.claude/settings.json` MCP wiring. Consult this before proposing any new memory/storage system on this machine — the gotchas section exists specifically to stop that mistake from recurring.
---

# Personal AI Memory Gateway

## Architecture, one paragraph
The knowledge-base MCP server (SQLite via `bun:sqlite`, entity-observation model, SHA256 call caching, REST API, CLI; Phase 0 audit found 2 entities and 0 observations — not the 62 projects originally claimed) is the single canonical retrieval authority. Headroom is transport, provider cache-control, and live-zone compression — plus a redundant native memory store that may also serve as a fallback retrieval source, but only when the knowledge base's health check has confirmed failure, never on latency or partial errors. Claude Mem is a read-only ingestion source: it keeps writing its own native data untouched, and a one-directional sync job feeds new observations into the knowledge base. No component writes back into Claude Mem. Capture writes (POST /capture, captureEvent()) go directly to KB only; Headroom's fallback state governs retrieval only, not writes.

## Phase map
Phase 0 — audit the existing knowledge-base system before building anything new; fix the Greptile credential exposure (rotate + move to Keychain); baseline idle resource usage (~1.5GB combined overhead threshold); configure Headroom as a login-only LaunchAgent.
Phase 1 — Headroom transport, native memory enabled, registered as health-check-gated fallback.
Phase 2 — extend the knowledge base's entity-observation model with new observation types (prompts, responses, tool calls, repo path, git branch, files touched, commands); redact secrets before write; capture only, no summarization or retrieval yet.
Phase 3 — read-only Claude Mem ingestion, 15-minute poll, dedupe by hash. Decision #6's confidence-delta>0.3 trigger is unimplementable (no confidence score exists in either system) — amended by decision #13: conflict = content-mismatch on same source ID, logged to `manual-review.json`, logging only, no KB mutation/deactivation this pass.
Phase 4 — multi-tool session-resume capsules (project, branch, last task, blockers, commands, files, decisions, do-not-touch list; 800–2000 tokens target, 3000 cap; `degraded: true` when sourced from Headroom's fallback). Claude Code and Codex confirmed via `headroom wrap`; Cursor is best-effort since it's an IDE extension and may lack an equivalent hook.
Phase 5 — local 7B–8B quantized model for summarization/classification/redaction only, never primary coding/reasoning.
Phase 6 — curated fine-tuning dataset export (5,000–20,000 verified examples, manually reviewed, plus eval set); training itself happens off this machine. Do not start before Phases 0–5 are stable.

## Memory record schema
```json
{
  "id": "mem_...",
  "type": "decision|preference|bugfix|command|project_fact|risk",
  "project": "string",
  "source": "claude_mem|headroom|terminal|manual",
  "created_at": "ISO-8601",
  "confidence": 0.0,
  "stability": "stable|volatile",
  "content": "string",
  "evidence": "string",
  "expires_at": "ISO-8601|null",
  "hash": "string"
}
```

## Standing decisions worth remembering
Same-machine redundancy (Claude Mem + Headroom + knowledge base all running) addresses service-crash failure, not machine-loss failure — off-machine backup is a deliberately separate, deliberately deferred phase, not solved by this architecture. Client-related context (Kenneth Harley, George Peppas engagements) currently gets no special handling in the capture layer — this was an explicit one-time risk acceptance, not a precedent for future engagements. The resource baseline gate exists because this machine also runs paid client work and background services can degrade it silently if unchecked.

## Gotchas — mistakes already made once on this project, don't repeat them

Don't propose a new memory backend before checking what already exists. The original plan (from an external advisor) proposed building a Headroom memory store, a new local event store, and a Claude Mem bridge as three separate systems — without knowing the knowledge-base MCP server already existed and already did most of that job. Always run the Phase 0 audit step before writing any new storage code, even if the request sounds like it needs new infrastructure.

Don't let "redundant storage" quietly become "multiple retrieval authorities." Turning on Headroom's native memory for redundancy is fine; using it as a silent fallback is not. Any session that resumes from the fallback path must be tagged `degraded: true` so it's visible, and the fallback must trigger only on a confirmed health-check failure — never on slowness or partial errors — or the two stores will drift and nobody will know which one a given session actually used.

Don't trust "enabled" as proof of "working." Headroom's memory feature being turned on doesn't mean it's persisting data. Verify with an actual write-then-read check before marking a phase done.

Don't treat same-machine redundancy as disaster recovery. Claude Mem, Headroom, and the knowledge base all living on the same internal SSD protects against a service crashing, not against the laptop dying, being lost, or its disk failing. If "disaster" includes machine loss, that needs its own off-machine backup phase with its own decision log — don't let it quietly stay unaddressed because same-machine redundancy already shipped.

Don't assume every AI tool supports the same session-start hook mechanism. Claude Code and Codex are CLI tools and support `headroom wrap`; Cursor is an IDE extension and may not have an equivalent hook at all. Verify per-tool rather than assuming parity, and don't let one tool's gap block shipping the other two.

Don't skip the resource baseline before stacking more background services. This machine runs paid client work. An unmonitored set of LaunchAgents (proxy, knowledge-base server, local model, embeddings) can degrade it without anyone noticing until a client deliverable is already late.

Don't fix an exposed credential by just rotating it in place. Rotating a token that's still stored in plaintext config repeats the same exposure with a new value. Move it to Keychain (or equivalent) while you're already touching the file.

Don't capture client-related context without checking confidentiality terms, and don't assume one risk-accepted decision covers future engagements. The "no special handling" call for Kenneth Harley and George Peppas was explicit and scoped to this build; a new client or a contract renewal is a new check, not an inherited exception.

Don't start Phase 6 on raw, unredacted, or unreviewed data. Fine-tuning bakes in whatever it's trained on, including noise, mistakes, and stale repo state. Only verified instruction-to-ideal-answer pairs and reviewed decision records are safe training data.
