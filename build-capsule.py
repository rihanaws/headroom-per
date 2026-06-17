#!/usr/bin/env python3
"""Phase 4: Session-resume capsule builder.

Queries the knowledge base for project-relevant observations and formats
a session-resume capsule for injection into Claude Code / Codex at session
start. Falls back to Headroom's HNSW memory on ConnectionRefusedError only
(per Decision #12). Sets degraded=true when operating from fallback.

Token budget: 800-2000 target, 3000 hard cap (per spec).
Usage:
    python3 build-capsule.py                   # auto-detect project from cwd
    python3 build-capsule.py --project myproj  # explicit project name
    python3 build-capsule.py --json            # output raw JSON instead of text
"""
import argparse
import asyncio
import errno
import http.client
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

KB_HOST = "127.0.0.1"
KB_PORT = 3333
KB_TIMEOUT = 2.0
HEADROOM_DB = Path("/Users/rihan/.headroom/memory.db")
HEADROOM_USER_ID = "rihan"

TOKEN_HARD_CAP = 3000
TOKEN_TARGET_MAX = 2000

try:
    from headroom.memory.backends.local import LocalBackend, LocalBackendConfig
    _HEADROOM_AVAILABLE = True
except ImportError:
    _HEADROOM_AVAILABLE = False


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[... truncated to fit token budget]"


def _git(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def _detect_context() -> tuple[str, str]:
    project = os.path.basename(_git(["git", "rev-parse", "--show-toplevel"]) or os.getcwd())
    branch = _git(["git", "branch", "--show-current"]) or "unknown"
    return project, branch


def _kb_search(query: str) -> Optional[dict]:
    conn = http.client.HTTPConnection(KB_HOST, KB_PORT, timeout=KB_TIMEOUT)
    try:
        conn.request("GET", f"/search?q={query}")
        res = conn.getresponse()
        if res.status == 200:
            return {"ok": True, "data": json.loads(res.read().decode())}
        return {"ok": False, "conn_refused": False, "error": f"HTTP {res.status}"}
    except ConnectionRefusedError:
        return {"ok": False, "conn_refused": True, "error": "connection refused"}
    except OSError as e:
        refused = e.errno == errno.ECONNREFUSED or "Connection refused" in str(e)
        return {"ok": False, "conn_refused": refused, "error": str(e)}
    except socket.timeout:
        return {"ok": False, "conn_refused": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "conn_refused": False, "error": str(e)}
    finally:
        conn.close()


async def _headroom_search(query: str, top_k: int = 10) -> list[str]:
    if not _HEADROOM_AVAILABLE:
        return []
    config = LocalBackendConfig(
        db_path=str(HEADROOM_DB),
        embedder_backend="onnx",
        embedder_model="all-MiniLM-L6-v2",
        vector_dimension=384,
    )
    backend = LocalBackend(config)
    await backend._ensure_initialized()
    try:
        results = await backend.search_memories(query=query, user_id=HEADROOM_USER_ID, top_k=top_k)
        return [getattr(r.memory, "content", "") for r in results]
    finally:
        await backend.close()


def _format_list(items: list[str], label: str, max_items: int = 5) -> str:
    if not items:
        return f"{label}: none recorded\n"
    lines = f"{label}:\n"
    for item in items[:max_items]:
        lines += f"  - {item.strip()}\n"
    return lines


def _build_from_kb_results(results: dict, project: str, branch: str) -> tuple[str, bool]:
    observations = results.get("observations", [])

    obs_contents = [o["content"] for o in observations if o.get("is_active") and o.get("content")]

    # Classify observations by keyword
    last_task = ""
    blockers: list[str] = []
    decisions: list[str] = []
    commands: list[str] = []
    files: list[str] = []
    do_not_touch: list[str] = []
    other: list[str] = []

    for c in obs_contents:
        cl = c.lower()
        if "blocker" in cl or "blocked" in cl:
            blockers.append(c)
        elif "decision" in cl or "decided" in cl:
            decisions.append(c)
        elif "do not touch" in cl or "don't touch" in cl or "do-not-touch" in cl:
            do_not_touch.append(c)
        elif any(k in cl for k in ["command", "ran ", "run ", "executed"]):
            commands.append(c)
        elif any(k in cl for k in ["file", "touched", "edited", "modified"]):
            files.append(c)
        else:
            other.append(c)

    last_task = (decisions + other + obs_contents)[:1]
    last_task = last_task[0] if last_task else "no recent task recorded"

    return _render_capsule(project, branch, last_task, blockers, decisions, commands, files, do_not_touch, degraded=False)


def _build_from_headroom(contents: list[str], project: str, branch: str) -> tuple[str, bool]:
    blockers: list[str] = []
    decisions: list[str] = []
    commands: list[str] = []
    files: list[str] = []
    do_not_touch: list[str] = []
    other: list[str] = []

    for c in contents:
        cl = c.lower()
        if "blocker" in cl or "blocked" in cl:
            blockers.append(c)
        elif "decision" in cl or "decided" in cl:
            decisions.append(c)
        elif "do not touch" in cl or "don't touch" in cl:
            do_not_touch.append(c)
        elif any(k in cl for k in ["command", "ran ", "run ", "executed"]):
            commands.append(c)
        elif any(k in cl for k in ["file", "touched", "edited", "modified"]):
            files.append(c)
        else:
            other.append(c)

    last_task = (decisions + other + contents)[:1]
    last_task = last_task[0] if last_task else "no recent task recorded (fallback memory)"

    return _render_capsule(project, branch, last_task, blockers, decisions, commands, files, do_not_touch, degraded=True)


def _render_capsule(
    project: str,
    branch: str,
    last_task: str,
    blockers: list[str],
    decisions: list[str],
    commands: list[str],
    files: list[str],
    do_not_touch: list[str],
    degraded: bool,
) -> tuple[str, bool]:
    degraded_banner = "\n⚠️  DEGRADED: KB unavailable — capsule built from Headroom fallback memory. Data may be stale.\n" if degraded else ""

    text = f"""--- SESSION RESUME CAPSULE ---{degraded_banner}
project:  {project}
branch:   {branch}

last task:
  {last_task.strip()}

{_format_list(blockers, "open blockers")}
{_format_list(decisions, "recent decisions")}
{_format_list(commands, "commands run")}
{_format_list(files, "files touched")}
{_format_list(do_not_touch, "do not touch")}
--- END CAPSULE ---
"""
    return _truncate_to_tokens(text, TOKEN_HARD_CAP), degraded


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build session-resume capsule from KB or Headroom fallback.")
    parser.add_argument("--project", "-p", default="", help="Project name (default: auto from git)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    args = parser.parse_args()

    project, branch = _detect_context()
    if args.project:
        project = args.project

    result = _kb_search(project)

    if result and result["ok"]:
        capsule_text, degraded = _build_from_kb_results(result["data"], project, branch)
        source = "knowledge_base"
    elif result and result.get("conn_refused"):
        if not _HEADROOM_AVAILABLE:
            print("Error: KB connection refused and headroom library unavailable for fallback.", file=sys.stderr)
            sys.exit(1)
        contents = await _headroom_search(project)
        capsule_text, degraded = _build_from_headroom(contents, project, branch)
        source = "headroom_memory"
    else:
        # Timeout or non-refused error — never fall back on latency (Decision #12)
        err = result.get("error", "unknown") if result else "no response"
        print(f"Error: KB query failed without connection refusal ({err}). No fallback per Decision #12.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps({"source": source, "degraded": degraded, "capsule": capsule_text}))
    else:
        print(capsule_text)


if __name__ == "__main__":
    asyncio.run(main())
