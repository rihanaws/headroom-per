# Implementation Spec: Personal AI Memory Gateway — Phase 0

**Status:** Accepted (post-interview)
**Date:** 2026-06-17
**Decider:** Rihan (sole)

## Problem
AI tooling (Claude Code, Codex, Cursor) currently has no shared memory across sessions or tools. Context is lost on `/clear`, repeated explanation costs tokens, and an existing knowledge-base system (SQLite/`bun:sqlite`, entity-observation model, MCP stdio server, REST API, CLI, 62 projects seeded) already solves part of this but isn't wired to Headroom or Claude Mem. Building a new memory store on top of it would create two competing sources of truth.

## Who it's for
Single user, personal dev workflow. Not client-facing, not multi-user, no access-control requirements beyond keeping secrets and client context from leaking into exports.

## Scope — this session
In scope: audit existing knowledge-base schema and MCP wiring, begin wiring Claude Mem read-only ingestion, fix the Greptile credential exposure, baseline resource usage, configure Headroom as a login-only LaunchAgent.
Out of scope (deferred to later phases): new local event store, local model, fine-tuning export, any client-data quarantine logic.

## Decision log

| # | Decision | Why | Alternative considered |
|---|----------|-----|------------------------|
| 1 | Knowledge-base is the single canonical memory store; Headroom is transport/compression only | Avoids two competing sources of truth | Headroom owns its own memory store — rejected, fragments retrieval |
| 2 | Claude Mem ingestion is read-only, one-directional into the knowledge base | Limits blast radius while schema is unproven | Bidirectional sync — rejected until ingestion is validated |
| 3 | LaunchAgents are login-only, not boot-time LaunchDaemons | Simpler, matches normal dev-machine usage; user confirmed | Boot-time LaunchDaemon — rejected, unnecessary for a dev workstation |
| 4 | Client-related context gets no special handling in the capture layer | User-accepted risk; revisit if engagement terms require separation later | Quarantine namespace — deferred, not built this session |
| 5 | Ingestion trigger: 15-min LaunchAgent poll + session-start query against already-ingested data | Balances freshness against latency and live-dependency risk | Poll-only or session-start-only — each has a gap the hybrid avoids |
| 6 | Conflict resolution: last-write-wins, flag to manual review if confidence delta > 0.3 | Simple default appropriate for single-user store; review queue catches real disagreements | Full reconciliation engine — overkill at this scale |
| 7 | Greptile credential: rotate token, move to macOS Keychain via `security` CLI | Fixes root cause, not just symptom, while already in the file | Rotate only — rejected, leaves next token equally exposed |
| 8 | Resource baseline gate: proceed if combined overhead < ~1.5GB RAM, negligible CPU at idle | This machine runs paid client work; protects it from background-service creep | No gate — rejected, removes the only check against silent resource creep |

## Step-by-step plan

**1. Audit existing knowledge-base system**
Read schema, entity-observation model, MCP server code, and REST/CLI interfaces at `/Users/rihan/all-coding-project` before changing anything. Decision already made (#1) — this step confirms the existing system can actually support the new observation types Phase 2 will need; if it can't, that's new information that should pause the plan, not get worked around.

**2. Fix Greptile credential exposure**
Rotate the exposed token. Store the new one in macOS Keychain; update the MCP server config to read it at runtime via `security find-generic-password`. Verify the old token is invalidated, not just replaced in config.

**3. Configure Headroom as a login-only LaunchAgent**
Proxy on `127.0.0.1:8787`, scoped to routing and provider cache-control optimization only — no memory responsibilities. Set `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`. Verify `/health` and `/stats` before moving on.

**4. Baseline resource usage**
Measure idle RAM/CPU with Headroom and the knowledge-base MCP server both running, nothing else added yet. Compare against the 1.5GB threshold (#8). If over, stop and reassess scope before Phase 3 adds more.

**5. Begin Claude Mem read-only ingestion**
Build the ingestion job per decisions #2 and #5: poll Claude Mem's store (`127.0.0.1:37701`) every 15 minutes, dedupe by hash against existing knowledge-base entries, write new observations through the knowledge base's existing API. Apply conflict resolution per decision #6. Do not write back to Claude Mem.

## Risk register

| Risk | Mitigation | Accepted residual risk |
|------|-----------|------------------------|
| Client confidentiality exposure via captured context | None applied this session | Accepted by user (decision #4) — revisit if engagement terms change |
| Resource contention with paid client work | Baseline gate before adding more services | Low, given the gate is enforced |
| Schema mismatch between Claude Mem and knowledge-base observation types | Read-only, one-directional ingestion limits damage | Low |
| Credential exposure recurring elsewhere in settings.json | Spot-checked Greptile only, not a full secrets audit | Medium — a full audit of `~/.claude/settings.json` is not in this session's scope |

## Acceptance criteria
Headroom `/health` and `/stats` return successfully with Claude Code routed through it. Greptile token is rotated, old one confirmed invalid, new one read from Keychain rather than plaintext. Resource baseline is measured and recorded, with a pass/fail against the 1.5GB threshold. Claude Mem ingestion job runs at least once successfully and writes at least one new observation into the existing knowledge base without errors.

## Explicitly deferred
New local event store (superseded — see decision #1), local model integration, session-resume capsule wiring, fine-tuning dataset export. These are Phases 1 (partially complete via step 3), 4, 5, and 6 of the broader plan and should not be started until this session's acceptance criteria are met.

## Reviewer checkpoint
Before starting ingestion wiring (step 5), confirm steps 1–4 are actually verified, not just attempted — the resource baseline gate in particular should block forward progress if it fails, not get silently skipped because the rest of the session is going well.
