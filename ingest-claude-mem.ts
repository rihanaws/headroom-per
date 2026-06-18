#!/usr/bin/env bun
/**
 * Claude Mem → Knowledge Base Ingestion Job
 *
 * Polls Claude Mem observations via HTTP, dedupes by SHA256 hash,
 * and writes new entries into the knowledge base through its SDK.
 *
 * Decisions applied:
 *   #2  — read-only, one-directional into KB (never writes back to Claude Mem)
 *   #5  — designed for 15-min LaunchAgent poll
 *   #13 — conflict detection only: same Claude Mem observation ID seen before
 *         with different content is logged to manual-review.json. No KB
 *         mutation, no deactivation — every conflict is a pending entry
 *         awaiting manual approval, never auto-resolved.
 */

import { createHash } from "crypto";

// ── Configuration ──────────────────────────────────────────────────
const CLAUDE_MEM_BASE = "http://127.0.0.1:37701";
const KB_API_BASE = "http://127.0.0.1:3333";
const OMLX_BASE = "http://127.0.0.1:8005";
const OMLX_MODEL = "Qwen3.5-4B-MLX-4bit";
const SUMMARIZE_THRESHOLD_CHARS = 1500;
const BATCH_SIZE = 50;
const HASH_LOG_PATH = "./ingestion-hashes.json";
const SOURCE_ID_LOG_PATH = "./ingestion-source-ids.json";
const MANUAL_REVIEW_PATH = "./manual-review.json";

// ── Types ──────────────────────────────────────────────────────────
interface ClaudeMemObservation {
  id: number;
  memory_session_id: string;
  project: string;
  platform_source: string;
  type: string;
  title: string;
  subtitle: string;
  narrative: string;
  facts: string;
  concepts: string;
  files_read: string;
  files_modified: string;
  prompt_number: number;
  created_at: string;
}

// ── Hash tracking (persistent across runs) ─────────────────────────
async function loadProcessedHashes(): Promise<Set<string>> {
  try {
    const file = Bun.file(HASH_LOG_PATH);
    if (await file.exists()) {
      const data = await file.json();
      return new Set(data.hashes || []);
    }
  } catch {
    // First run or corrupted file — start fresh
  }
  return new Set();
}

async function saveProcessedHashes(hashes: Set<string>): Promise<void> {
  await Bun.write(
    HASH_LOG_PATH,
    JSON.stringify({ hashes: [...hashes], updated_at: new Date().toISOString() }, null, 2)
  );
}

function hashObservation(obs: ClaudeMemObservation): string {
  const payload = JSON.stringify({
    id: obs.id,
    project: obs.project,
    title: obs.title,
    narrative: obs.narrative,
    facts: obs.facts,
  });
  return createHash("sha256").update(payload).digest("hex");
}

// ── Source-ID tracking (last hash written per Claude Mem observation ID) ──
interface SourceIdRecord {
  hash: string;
  content: string;
  written_at: string;
}

async function loadSourceIdLog(): Promise<Map<number, SourceIdRecord>> {
  try {
    const file = Bun.file(SOURCE_ID_LOG_PATH);
    if (await file.exists()) {
      const data = (await file.json()) as Record<string, SourceIdRecord>;
      return new Map(Object.entries(data).map(([id, rec]) => [Number(id), rec]));
    }
  } catch {
    // First run or corrupted file — start fresh
  }
  return new Map();
}

async function saveSourceIdLog(log: Map<number, SourceIdRecord>): Promise<void> {
  const obj = Object.fromEntries(log);
  await Bun.write(SOURCE_ID_LOG_PATH, JSON.stringify(obj, null, 2));
}

// ── Manual review log (conflicts only — never auto-resolved) ──────────
interface ManualReviewEntry {
  source_id: number;
  project: string;
  detected_at: string;
  previous: { hash: string; content: string; written_at: string };
  incoming: { hash: string; content: string };
  pending_action: string;
}

async function appendManualReview(entry: ManualReviewEntry): Promise<void> {
  let entries: ManualReviewEntry[] = [];
  try {
    const file = Bun.file(MANUAL_REVIEW_PATH);
    if (await file.exists()) {
      entries = (await file.json()) as ManualReviewEntry[];
    }
  } catch {
    // First conflict or corrupted file — start fresh
  }
  entries.push(entry);
  await Bun.write(MANUAL_REVIEW_PATH, JSON.stringify(entries, null, 2));
}

// ── KB API helpers ─────────────────────────────────────────────────
async function ensureEntity(name: string, type: string): Promise<void> {
  try {
    await fetch(`${KB_API_BASE}/entities`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, type }),
    });
  } catch {
    // Entity may already exist (INSERT OR IGNORE) — that's fine
  }
}

async function summarizeIfLong(content: string): Promise<string> {
  if (content.length <= SUMMARIZE_THRESHOLD_CHARS) return content;
  try {
    const res = await fetch(`${OMLX_BASE}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: OMLX_MODEL,
        messages: [
          {
            role: "user",
            content: `Summarize the following dev log entry in 2-3 sentences, keeping concrete facts (file names, decisions, numbers):\n\n${content}`,
          },
        ],
        max_tokens: 200,
      }),
    });
    if (!res.ok) return content;
    const data = await res.json();
    const summary = data?.choices?.[0]?.message?.content;
    return typeof summary === "string" && summary.trim() ? summary.trim() : content;
  } catch {
    return content;
  }
}

async function addObservation(entityName: string, content: string): Promise<boolean> {
  try {
    const res = await fetch(`${KB_API_BASE}/observations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entityName, content }),
    });
    return res.ok;
  } catch (err) {
    console.error(`  Failed to write observation for ${entityName}:`, err);
    return false;
  }
}

// ── Main ingestion loop ────────────────────────────────────────────
async function ingest(): Promise<void> {
  console.log(`[${new Date().toISOString()}] Starting Claude Mem → KB ingestion`);

  // 1. Check Claude Mem health
  try {
    const health = await fetch(`${CLAUDE_MEM_BASE}/health`);
    if (!health.ok) {
      console.error("Claude Mem health check failed, aborting.");
      process.exit(1);
    }
  } catch (err) {
    console.error("Claude Mem unreachable:", err);
    process.exit(1);
  }

  // 2. Check KB REST API health (try a simple GET)
  try {
    const graphRes = await fetch(`${KB_API_BASE}/graph`);
    if (!graphRes.ok) {
      console.error("Knowledge Base REST API unreachable, aborting. Is `bun run api` running?");
      process.exit(1);
    }
  } catch (err) {
    console.error("Knowledge Base REST API unreachable:", err);
    console.error("Start it with: cd /Users/rihan/all-coding-project/knowledge-base && bun run api");
    process.exit(1);
  }

  // 3. Load previously processed hashes and source-ID log
  const processedHashes = await loadProcessedHashes();
  const sourceIdLog = await loadSourceIdLog();
  console.log(`  Loaded ${processedHashes.size} previously processed hashes`);
  console.log(`  Loaded ${sourceIdLog.size} tracked source IDs`);

  // 4. Fetch observations from Claude Mem in batches
  let offset = 0;
  let hasMore = true;
  let totalFetched = 0;
  let totalNew = 0;
  let totalWritten = 0;
  let totalConflicts = 0;

  while (hasMore) {
    const url = `${CLAUDE_MEM_BASE}/api/observations?limit=${BATCH_SIZE}&offset=${offset}`;
    const res = await fetch(url);
    if (!res.ok) {
      console.error(`  Failed to fetch observations at offset ${offset}`);
      break;
    }

    const data = (await res.json()) as { items: ClaudeMemObservation[]; hasMore: boolean };
    totalFetched += data.items.length;

    for (const obs of data.items) {
      const hash = hashObservation(obs);

      // Dedupe
      if (processedHashes.has(hash)) {
        continue;
      }

      totalNew++;

      // Use project name as entity, or default
      const entityName = obs.project || "unknown-project";
      await ensureEntity(entityName, "Project");

      // Build a structured observation content string
      const content = [
        `[${obs.type}] ${obs.title}`,
        obs.subtitle ? `  ${obs.subtitle}` : null,
        obs.narrative || null,
        obs.facts ? `  Facts: ${obs.facts}` : null,
        `  Source: claude-mem #${obs.id} (${obs.platform_source}, ${obs.created_at})`,
      ]
        .filter(Boolean)
        .join("\n");

      // Decision #13 — conflict detection only. Same source ID seen before
      // with a different hash means the content changed since last write.
      // Logged to manual-review.json as a pending action; never auto-resolved
      // or deactivated. The new content is still written through (last-write-
      // wins for "what's active in KB"), but the conflict is now visible.
      const previous = sourceIdLog.get(obs.id);
      if (previous && previous.hash !== hash) {
        totalConflicts++;
        await appendManualReview({
          source_id: obs.id,
          project: entityName,
          detected_at: new Date().toISOString(),
          previous: {
            hash: previous.hash,
            content: previous.content,
            written_at: previous.written_at,
          },
          incoming: { hash, content },
          pending_action: "review and decide whether previous observation should be deactivated (no automatic deactivation implemented)",
        });
        console.log(`  Conflict detected on source #${obs.id} — logged to ${MANUAL_REVIEW_PATH}`);
      }

      const summarized = await summarizeIfLong(content);
      const written = await addObservation(entityName, summarized);
      if (written) {
        totalWritten++;
        processedHashes.add(hash);
        sourceIdLog.set(obs.id, { hash, content, written_at: new Date().toISOString() });
      }
    }

    hasMore = data.hasMore;
    offset += BATCH_SIZE;
  }

  // 5. Persist hash and source-ID logs
  await saveProcessedHashes(processedHashes);
  await saveSourceIdLog(sourceIdLog);

  console.log(
    `  Done. Fetched: ${totalFetched}, New: ${totalNew}, Written to KB: ${totalWritten}, Conflicts: ${totalConflicts}`
  );
  console.log(`[${new Date().toISOString()}] Ingestion complete`);
}

ingest().catch((err) => {
  console.error("Ingestion failed:", err);
  process.exit(1);
});
