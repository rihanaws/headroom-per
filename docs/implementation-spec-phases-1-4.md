# Implementation Spec: Personal AI Memory Gateway — Phases 1–4 (Amended)

**Status:** Accepted (post-interview)
**Date:** 2026-06-17
**Decider:** Rihan (sole)

## Problem
No shared memory or continuity across AI tools today; Phase 0 established the knowledge base as canonical for retrieval while keeping Claude Mem and Headroom's own storage fully intact for redundancy.

## Who it's for
Single user, personal dev workflow.

## Scope this phase set
In: Headroom transport plus redundant native memory, knowledge-base observation-type extension, Claude Mem read-only ingestion, multi-tool session-resume wiring (Claude Code and Codex confirmed, Cursor best-effort).
Out: local model (Phase 5), fine-tuning export (Phase 6), off-machine backup build (scoped only below, not built this pass).

## Decision log — amendments and additions

| # | Decision | Why | Cost / risk flagged |
|---|----------|-----|----------------------|
| 9 | Same-machine redundancy now; off-machine backup deferred to a follow-on phase | Solves the service-crash disaster case immediately without blocking on backup design choices that deserve their own pass | True machine-loss protection is not yet in place — accepted as open until follow-on |
| 10 | (amends #1) Headroom's native memory is turned on and used as a fallback retrieval source, gated strictly behind a knowledge-base health-check failure | Matches requested redundancy; gating on confirmed failure (not latency/partial errors) avoids flapping between sources | Headroom's memory and the knowledge base will drift over time by design — fallback sessions must be visibly tagged, not silent |
| 11 | Phase 4 wiring targets Claude Code, Codex, and Cursor simultaneously | Requested scope | Cursor is an IDE extension and may lack an equivalent session-start hook; if so, ship the other two and treat Cursor separately rather than forcing a workaround |

## Step-by-step plan

**Phase 1 — Headroom (revised)**
Login-only LaunchAgent, proxy on `127.0.0.1:8787`, routing plus provider cache-control plus live-zone compression as before. Enable Headroom's native memory feature so it persists its own redundant copy of session/context data, the same role Claude Mem already plays. Register Headroom's memory as a fallback retrieval source, gated strictly behind a knowledge-base health-check failure. Verify `/health` and `/stats`, and separately verify Headroom's memory feature is actually persisting data — don't treat "enabled" as proof of "working."

**Phase 2 — Knowledge-base extension (unchanged)**
Extend the existing entity-observation model with new observation types for prompt/response summaries, tool calls, repo path, git branch, files touched, commands run. Redaction pass strips secrets before write. Capture only.

**Phase 3 — Claude Mem ingestion (unchanged)**
15-minute poll against `127.0.0.1:37701`, dedupe by hash, one-directional write into the knowledge base. Conflicts resolved last-write-wins, flagged to manual review if confidence delta exceeds 0.3.

**Phase 4 — Multi-tool session resume (revised scope)**
Wire session-start hooks for Claude Code and Codex via `headroom wrap`, since both support the wrapper pattern. Attempt the same for Cursor; if no equivalent mechanism exists, document the gap rather than forcing a fit. Resume capsule format unchanged — project, branch, last task, blockers, commands run, files touched, decisions, do-not-touch list, 800–2000 tokens target, 3000 hard cap — with one addition: a `degraded` boolean field set true whenever the capsule was built from Headroom's fallback memory instead of the canonical knowledge base, so you always know which source you got.

## Risk register additions

| Risk | Mitigation | Residual |
|------|-----------|----------|
| Retrieval drift between knowledge base and Headroom fallback memory | `degraded` flag + health-check-gated triggering only | Medium — inherent to having a fallback at all |
| Cursor may lack the wrapper hook pattern | Ship Claude Code/Codex now, investigate Cursor separately | Low — smaller initial win, not a broken build |
| Off-machine backup not yet built | Explicitly deferred, not forgotten | Accepted this round |

## Acceptance criteria
Headroom's own memory store demonstrably persists data across at least one full session. A deliberate knowledge-base health-check failure correctly triggers the fallback and tags the capsule `degraded: true`. Claude Code and Codex both receive an injected resume capsule on session start after `/clear`. Cursor either works the same way or the gap is documented with a one-line reason why not.

## Explicitly deferred — off-machine backup (scoped, not built)
When this is picked up, it needs its own decision log: backup target (git remote, cloud storage, or external drive), frequency, what's excluded beyond what's already redacted, and a restore-test cadence — a backup that's never been restored from isn't a verified backup. Don't build this opportunistically inside Phase 1–4 work; it deserves its own pass.

## Reviewer checkpoint
Before wiring Phase 4 across all three tools, confirm Phase 1's fallback path actually fails over correctly under a deliberate test. Wiring multi-tool resume on top of an unverified fallback bakes any bug there into three integrations instead of one.
