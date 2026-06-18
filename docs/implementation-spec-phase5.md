
# Implementation Spec: Personal AI Memory Gateway — Phase 5

**Status:** Accepted
**Date:** 2026-06-18
**Decider:** Rihan (sole)

## Problem
Phases 0–4 route all reasoning through Claude/Codex via Headroom. Some tasks (summarization, log classification, secret redaction) don't need frontier-model reasoning and can run locally for zero API cost — but only if scoped tightly enough not to become a second reasoning path.

## Who it's for
Single user, personal dev workflow.

## Scope this phase
In: wiring a local quantized model into low-risk, non-reasoning tasks only — summarization, log classification, secret redaction assist.
Out: any coding/architecture/debugging reasoning (stays on Claude/Codex through Headroom), fine-tuning (Phase 6), new model downloads.

## Decision log

| # | Decision | Why | Cost / risk flagged |
|---|----------|-----|----------------------|
| 15 | Use already-running oMLX server (`127.0.0.1:8005`, model `Qwen3.5-4B-MLX-4bit`) instead of pulling a 7B–8B model per the brief's literal wording | Brief names 7B–8B as a suggested class, not a hard requirement. Machine has 19.3GB RAM, ~4.3GB free at last check; oMLX itself reports an 11GB ceiling. Pulling a bigger model risks OOM against Headroom + KB + Claude Mem + oMLX already running. 4B is already loaded, already verified serving | Smaller model = weaker summarization/classification quality than 7B–8B would give; acceptable since this phase explicitly excludes reasoning-critical work |
| 16 | oMLX accessed via its OpenAI-compatible `/v1/chat/completions` endpoint, not a new client library | oMLX already exposes `/v1/models` in OpenAI schema (confirmed via curl); existing knowledge-base/Headroom code likely already has an OpenAI-shaped HTTP client pattern to extend rather than adding a new dependency | None identified |
| 17 | Local-model calls are a new, distinct code path — not routed through Headroom | Headroom is explicitly scoped to Claude/Codex provider traffic (Phase 1). Routing local-model calls through it would blur that boundary for no benefit, since there's no provider cost or cache-control concern for a local model | None identified |
| 18 | Replicated `redact()` regex patterns directly into `ingest-claude-mem.ts` instead of importing `knowledge-base/src/redact.ts` cross-repo | `ingest-claude-mem.ts` has no `package.json`/shared deps with the `knowledge-base` repo; a cross-repo import would add new dependency coupling outside what this phase calls for. Discovered while wiring redaction-assist: `POST /observations` (the endpoint this script writes through) had **zero redaction** — only `/capture` (Phase 2) was gated. Fixed by applying regex `redact()` to raw content before summarization, then `redactionAssist()` (oMLX, flag-only) on the redacted text, then `addObservation()`. Order matters — redact must run before summarize, or a model paraphrase could reintroduce a secret it saw in raw content | Two copies of the same regex patterns now exist (`knowledge-base/src/redact.ts` and `ingest-claude-mem.ts`) — must update both if patterns change. oMLX redaction-assist tested live and under-flags even obvious cases (`"my password is hunter2"` → `"no"`); shipped as-is per spec — assist is advisory only, the regex pass is the actual enforced gate and is verified working |

## Step-by-step plan
1. Confirm oMLX `/v1/chat/completions` contract directly (request/response shape) before writing any client code.
2. Add a small local-model client (plain HTTP, no new dependency) scoped to three call sites: summarize text, classify a log line, suggest redaction candidates.
3. Wire summarization into the Claude Mem ingestion path (Phase 3) only if/where it currently has no summarization step — extend existing ingestion, don't duplicate it.
4. Secret redaction assist supplements, never replaces, the existing regex-based `redact.ts` pass (Phase 2) — local model flags candidates, regex pass remains the enforced gate before write.
5. No new LaunchAgent, no new storage. oMLX is already running as a separate app the user controls directly (Start/Stop in its own UI) — this phase does not manage its lifecycle.

## Risk register

| Risk | Mitigation | Residual |
|------|-----------|----------|
| oMLX not running when called | Health-check `/health` before use, fail closed (skip local-model step, don't block the primary path) | Low — primary Claude/Codex path unaffected either way |
| Local model hallucinates a classification/summary | Used only for low-stakes assist (summarization, classification) never for secret-redaction enforcement (regex remains the gate) | Low by design |
| RAM pressure from concurrent oMLX + Headroom + KB + Claude Mem | Already measured: 11GB ceiling reported by oMLX, model loaded at 3.2GB, machine has 19.3GB total | Monitor if oMLX model is ever swapped larger |

## Acceptance criteria
- oMLX `/health` and `/v1/chat/completions` reachable and verified with a real request/response, not assumed from `/v1/models` alone.
- At least one of the three call sites (summarize / classify / redaction-assist) wired end-to-end and exercised against real data.
- No change to Headroom routing scope or the existing regex redaction gate.
- `progress.md` updated with what was actually verified vs. what's deferred.
