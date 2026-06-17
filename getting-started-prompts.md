# Getting Started: Personal AI Memory Gateway with Claude Code

## What you need before opening Claude Code
Claude Code installed and authenticated (`claude` works from a terminal). Headroom's repo available with its existing `.venv` (`[proxy,relevance]` already installed). The knowledge-base project's actual path on disk, since Claude Code will need to read and extend it. Claude Mem already running and reachable (health endpoint near `127.0.0.1:37701`). Git installed, since session continuity depends on commits as checkpoints.

## Folder structure
Create the blank folder, then build this inside it before the first Claude Code session:

```
headroom-memory-gateway/
├── CLAUDE.md
├── progress.md                          (empty file to start)
├── docs/
│   ├── personal-ai-memory-gateway-agent-brief-v2.md
│   ├── implementation-spec-phase0.md
│   └── implementation-spec-phases-1-4.md
└── .claude/
    └── skills/
        └── personal-ai-memory-gateway/
            └── SKILL.md
```

Copy the four files already generated in this conversation into the matching spots: `CLAUDE.md` to the root, the three spec docs into `docs/`, and `personal-ai-memory-gateway-SKILL.md` into `.claude/skills/personal-ai-memory-gateway/`, renamed to `SKILL.md`. Then run `git init` and an initial commit before opening Claude Code, so the first checkpoint isn't empty.

## The prompts, one per phase

Run these in order. Don't start the next one until the current phase's acceptance criteria (in the matching spec doc) are actually verified — Claude Code will tell you what it checked, but it's worth glancing at the output yourself before moving on, especially for Phase 0's credential fix and Phase 1's fallback test.

**Phase 0 — kickoff prompt:**
```
Read CLAUDE.md, then read docs/implementation-spec-phase0.md in full.
Execute Phase 0 only: investigate the existing knowledge-base system,
fix the Greptile credential exposure by rotating it and moving it to
macOS Keychain, baseline idle resource usage, and configure Headroom
as a login-only LaunchAgent. Do not start Phase 1 until every
acceptance criterion in implementation-spec-phase0.md is independently
verified. Report what you actually verified, not what you attempted.
```

**Phase 1 — kickoff prompt:**
```
Read docs/implementation-spec-phases-1-4.md, Phase 1 section only.
Implement Headroom's login-only LaunchAgent with native memory enabled
and registered as a fallback retrieval source per decision #10 in that
doc. Verify /health, /stats, and that Headroom's memory feature is
actually persisting data with a real write-then-read check before
reporting this phase done.
```

**Phase 2 — kickoff prompt:**
```
Read docs/implementation-spec-phases-1-4.md, Phase 2 section. Extend
the existing knowledge-base entity-observation model with the new
observation types described there. Add the secret-redaction pass
before any write. This phase captures only — do not add
summarization, retrieval, or training logic yet.
```

**Phase 3 — kickoff prompt:**
```
Read docs/implementation-spec-phases-1-4.md, Phase 3 section. Build
the read-only Claude Mem ingestion job: 15-minute poll, dedupe by
hash, write through the knowledge base's existing API, one-directional
only. Apply the last-write-wins-plus-confidence-flag conflict rule
from decision #6 in the Phase 0 doc.
```

**Phase 4 — kickoff prompt:**
```
Read docs/implementation-spec-phases-1-4.md, Phase 4 section. Wire
session-start hooks for Claude Code and Codex via headroom wrap. Try
the same for Cursor; if there's no equivalent hook mechanism, document
why and stop there rather than forcing a workaround. Add the degraded
field to the resume capsule per decision #10.
```

Phases 5 and 6 are intentionally not included here — they're gated behind Phases 0–4 being stable and verified, per the standing decision in the skill and the brief.

## After each phase
Claude Code should already do this per `CLAUDE.md`, but it's worth confirming: a commit exists for the phase, and `progress.md` reflects what's done and what's next. If either is missing, that's a sign the phase wasn't actually closed out, regardless of what the chat output claimed.
