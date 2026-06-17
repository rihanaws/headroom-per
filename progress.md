# Progress

## Phase 0 — COMPLETE (3 of 4 acceptance criteria met)

### Verified results

1. **✅ Headroom `/health` and `/stats` return successfully** with Claude Code routed through it.
   - `/health` → `status=healthy, ready=True, version=0.26.1`
   - `/stats` → returns compression stats, cost breakdown, request counts
   - `ANTHROPIC_BASE_URL=http://127.0.0.1:8787` confirmed in shell
   - LaunchAgent installed: `~/Library/LaunchAgents/com.headroom.default.plist` (persistent-service, login-only)

2. **⏭️ Greptile token rotation — SKIPPED** (see tracked risk below)

3. **✅ Resource baseline measured and passes 1.5GB gate.**
   - Headroom proxy: 16.7 MB RSS
   - Headroom MCP serve: 5.2 MB RSS
   - Claude Mem worker: 69.6 MB RSS
   - KB MCP server: 0 MB (stdio, launched on demand)
   - **Combined idle: 91.6 MB** — well under 1,536 MB threshold

4. **✅ Claude Mem ingestion job ran successfully.**
   - First run: fetched 574 observations, wrote 574 to KB (0 → 574 observations, 2 → 13 entities)
   - Second run: fetched 574, wrote 0 (deduplication confirmed)
   - Hash log persisted to `ingestion-hashes.json`

### Tracked risk (not silently skipped)
- **Greptile credential exposure**: API token stored in plaintext in `~/.claude/` plugin config area. Exposed since at least the Greptile plugin was first configured. User explicitly deferred rotation and Keychain migration during this session. **Revisit trigger**: before enabling any new MCP server that reads `~/.claude/settings.json`, before sharing config with another machine, or at the start of Phase 1 if time allows.

### Documentation corrections applied
- SKILL.md: "62 projects seeded" → "Phase 0 audit found 2 entities and 0 observations"

## Phase 1 — COMPLETE (2 of 2 acceptance criteria met)

### Verified results
1. **✅ Headroom memory store persists data across a hard process kill (`kill -9`).**
   - Verified that a test memory entry written to `memory.db` survives a hard `kill -9` of the `headroom` process and is successfully read back using `test_persistence.py`.
2. **✅ Deliberate knowledge-base health-check failure triggers fallback and tags capsule `degraded: true`.**
   - Created [retrieve_with_fallback.py](file:///Users/rihan/Downloads/rihan-personal-ai/retrieve_with_fallback.py).
   - Under healthy KB API: successfully returns results with `degraded: false`.
   - Under offline KB (`ConnectionRefusedError`): successfully falls back to Headroom's persistent HNSW memory backend and sets `degraded: true`.
   - Under hung KB / latency (socket timeout): correctly gates failover (rejects fallback), exits with code 1, and prints error message to stderr.

### Infrastructure fix applied (unblocked persistence)
- **Bug in `headroom/memory/adapters/hnsw.py`**: `HNSWVectorIndex.__init__` was correctly auto-saving to `.hnsw` and `.meta` files but never called `self.load_index()` on startup — so every cold start lost all prior data, making the index appear to persist while actually being empty after any restart. Patched `__init__` to call `load_index()` when the `.hnsw` file already exists. Without this fix, the `kill -9` persistence test would always fail regardless of HNSW write behavior.
  - **File**: `/Users/rihan/all-coding-project/headroom/headroom/memory/adapters/hnsw.py`
  - **Note for future sessions**: Do not assume Headroom's memory adapter works end-to-end before verifying with an actual write-then-read-after-restart. This machine hit that case and the fix was non-obvious.

### Security check: autocsr test run
- `retrieve_with_fallback.py` is **read-only** — it calls `search_memories()` and `check_kb_health()` only, with no write path to Headroom's memory store. The test run with `--project autocsr` queried what was already in the HNSW index (`"Phase 1 hard kill persistence test: this must survive."`) and the KB's `/graph` endpoint. No client observation was written into Headroom's fallback store.
- Decision #4 (no special handling for client context) does not apply here. No client data entered the fallback store.

### What's next
- Phase 3: Read-only Claude Mem ingestion, 15-minute poll, dedupe by hash, last-write-wins conflict resolution.

## Phase 2 — COMPLETE (4 of 4 acceptance criteria met)

### Verified results
1. **✅ `POST /capture` with a `prompt_response` payload writes a redacted observation to KB.**
   - `{"message":"Event captured"}` returned with HTTP 201.
   - Observation stored at id=723, `observation_type=prompt_response`, `content_hash` populated.

2. **✅ `observation_type` column exists and is populated on new writes.**
   - SQLite confirmed: `observation_type='prompt_response'` on the new row.
   - `content_hash` SHA-256 hex confirmed present.

3. **✅ All 574 existing observations still readable via `/graph` with `observation_type='general'`.**
   - `SELECT observation_type, COUNT(*) FROM observations GROUP BY observation_type` → `general: 574, prompt_response: 1` — no existing rows affected.

4. **✅ A payload containing real API key patterns is stored with `[REDACTED]` — no raw secrets in DB.**
   - Input: `sk-ant-abc123FAKEKEY`, `ANTHROPIC_API_KEY=sk-ant-deadbeef12345`, `Bearer eyJ...`, `MY_SECRET=super-secret-value-here`
   - Stored content: all four replaced with `[REDACTED]`. `Contains raw secrets: false`.

### Files changed
- `knowledge-base/src/redact.ts` — NEW: redaction module (Bearer, sk-/pk- prefixes, env var secrets, SSH keys, DB passwords, GitHub PATs)
- `knowledge-base/src/db.ts` — additive `ALTER TABLE` for `observation_type TEXT DEFAULT 'general'` and `content_hash TEXT` columns + two new indices
- `knowledge-base/src/adapters/memory-adapter.ts` — added `addObservationTyped()` to interface and `SQLiteMemoryAdapter`
- `knowledge-base/src/graph.ts` — added `CaptureEvent` interface, `ObservationType` type, `captureEvent()` function
- `knowledge-base/src/rest-api.ts` — added `POST /capture` route
- `knowledge-base/src/mcp-server.ts` — added `capture_event` MCP tool

### Security note: Greptile token coverage confirmed
The tracked Greptile credential is stored as `Authorization: Bearer <token>` in `.mcp.json`. The `Bearer\s+...` pattern in `redact.ts` covers this format. Any observation containing that token would be redacted before write.

### What's next
- Phase 3: Read-only Claude Mem ingestion, 15-minute poll, dedupe by `content_hash`, last-write-wins.
