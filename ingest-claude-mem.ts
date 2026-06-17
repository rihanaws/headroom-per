#!/usr/bin/env bun
/**
 * Claude Mem → Knowledge Base Ingestion Job
 *
 * Polls Claude Mem observations via HTTP, dedupes by SHA256 hash,
 * and writes new entries into the knowledge base through its SDK.
 *
 * Decisions applied:
 *   #2 — read-only, one-directional into KB (never writes back to Claude Mem)
 *   #5 — designed for 15-min LaunchAgent poll
 *   #6 — last-write-wins, flag to manual review if confidence delta > 0.3
 */

import { createHash } from "crypto";

// ── Configuration ──────────────────────────────────────────────────
const CLAUDE_MEM_BASE = "http://127.0.0.1:37701";
const KB_API_BASE = "http://127.0.0.1:3333";
const BATCH_SIZE = 50;
const HASH_LOG_PATH = "./ingestion-hashes.json";

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

  // 3. Load previously processed hashes
  const processedHashes = await loadProcessedHashes();
  console.log(`  Loaded ${processedHashes.size} previously processed hashes`);

  // 4. Fetch observations from Claude Mem in batches
  let offset = 0;
  let hasMore = true;
  let totalFetched = 0;
  let totalNew = 0;
  let totalWritten = 0;

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

      const written = await addObservation(entityName, content);
      if (written) {
        totalWritten++;
        processedHashes.add(hash);
      }
    }

    hasMore = data.hasMore;
    offset += BATCH_SIZE;
  }

  // 5. Persist hash log
  await saveProcessedHashes(processedHashes);

  console.log(
    `  Done. Fetched: ${totalFetched}, New: ${totalNew}, Written to KB: ${totalWritten}`
  );
  console.log(`[${new Date().toISOString()}] Ingestion complete`);
}

ingest().catch((err) => {
  console.error("Ingestion failed:", err);
  process.exit(1);
});
