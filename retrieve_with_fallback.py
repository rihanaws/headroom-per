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

# Try to import headroom components (using the headroom virtual environment)
try:
    from headroom.memory.backends.local import LocalBackend, LocalBackendConfig
except ImportError:
    print("Error: headroom library not found in Python path. Please run this script using Headroom's .venv python interpreter.", file=sys.stderr)
    sys.exit(1)

def get_git_branch():
    try:
        return subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL).decode("utf-8").strip()
    except Exception:
        return "main"

def get_project_name():
    return os.path.basename(os.getcwd())

def check_kb_health(host="127.0.0.1", port=3333, timeout=2.0):
    """
    Checks the KB health.
    Returns a dict with status details.
    """
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", "/graph")
        res = conn.getresponse()
        if res.status == 200:
            data = json.loads(res.read().decode('utf-8'))
            return {
                "success": True,
                "conn_refused": False,
                "data": data,
                "error": None
            }
        else:
            return {
                "success": False,
                "conn_refused": False,
                "data": None,
                "error": f"HTTP status {res.status}"
            }
    except socket.timeout as e:
        return {
            "success": False,
            "conn_refused": False,
            "data": None,
            "error": f"Socket timeout: {e}"
        }
    except ConnectionRefusedError as e:
        return {
            "success": False,
            "conn_refused": True,
            "data": None,
            "error": f"Connection refused: {e}"
        }
    except OSError as e:
        is_refused = (e.errno == errno.ECONNREFUSED) or ("Connection refused" in str(e))
        return {
            "success": False,
            "conn_refused": is_refused,
            "data": None,
            "error": f"OS Error: {e}"
        }
    except Exception as e:
        return {
            "success": False,
            "conn_refused": False,
            "data": None,
            "error": f"Unexpected error: {e}"
        }
    finally:
        conn.close()

async def query_headroom(db_path, query, user_id):
    config = LocalBackendConfig(
        db_path=db_path,
        embedder_backend="onnx",
        embedder_model="all-MiniLM-L6-v2",
        vector_dimension=384,
    )
    backend = LocalBackend(config)
    await backend._ensure_initialized()
    try:
        results = await backend.search_memories(
            query=query,
            user_id=user_id,
            top_k=5,
        )
        return results
    finally:
        await backend.close()

def build_capsule_from_kb(kb_data, project, branch):
    entities = kb_data.get("entities", [])
    observations = kb_data.get("observations", [])
    
    project_obs = []
    for obs in observations:
        entity_name = obs.get("entity_name", "")
        if entity_name.lower() == project.lower():
            project_obs.append(obs.get("content", ""))
            
    # If no specific project matches, grab recently added observations
    if not project_obs and observations:
        project_obs = [obs.get("content", "") for obs in observations[:5]]
        
    last_task = "Unknown (no matching observations)"
    blockers = "None recorded"
    decisions = []
    commands_run = []
    files_touched = []
    do_not_touch = []
    
    for obs in project_obs:
        obs_lower = obs.lower()
        if "blocker" in obs_lower:
            blockers = obs
        if "decision" in obs_lower or "change" in obs_lower:
            decisions.append(obs)
        if "command" in obs_lower or "run" in obs_lower:
            commands_run.append(obs)
        if "file" in obs_lower or "touch" in obs_lower:
            files_touched.append(obs)
            
    if decisions:
        last_task = decisions[0]
    elif project_obs:
        last_task = project_obs[0]
        
    capsule = {
        "project": project,
        "branch": branch,
        "last_task": last_task,
        "blockers": blockers,
        "commands_run": commands_run[:5],
        "files_touched": files_touched[:5],
        "decisions": decisions[:5],
        "do_not_touch": do_not_touch,
        "degraded": False,
        "raw_observations": project_obs[:10]
    }
    return capsule

def build_capsule_from_headroom(headroom_results, project, branch):
    last_task = "Unknown (fallback memory)"
    blockers = "None recorded"
    decisions = []
    commands_run = []
    files_touched = []
    do_not_touch = []
    raw_mems = []
    
    for r in headroom_results:
        content = getattr(r.memory, 'content', '')
        raw_mems.append(content)
        content_lower = content.lower()
        if "blocker" in content_lower:
            blockers = content
        if "decision" in content_lower:
            decisions.append(content)
        if "run" in content_lower or "command" in content_lower:
            commands_run.append(content)
        if "file" in content_lower or "touch" in content_lower:
            files_touched.append(content)
            
    if decisions:
        last_task = decisions[0]
    elif raw_mems:
        last_task = raw_mems[0]
        
    capsule = {
        "project": project,
        "branch": branch,
        "last_task": last_task,
        "blockers": blockers,
        "commands_run": commands_run[:5],
        "files_touched": files_touched[:5],
        "decisions": decisions[:5],
        "do_not_touch": do_not_touch,
        "degraded": True,
        "raw_observations": raw_mems
    }
    return capsule

async def main():
    parser = argparse.ArgumentParser(description="Retrieve session-resume capsule with fallback.")
    parser.add_argument("--query", "-q", default="", help="Query for retrieval")
    parser.add_argument("--user-id", "-u", default="rihan-test", help="User ID")
    parser.add_argument("--project", "-p", default="", help="Project name (defaults to current folder name)")
    parser.add_argument("--db-path", default="/Users/rihan/.headroom/memory.db", help="Path to Headroom local memory DB")
    parser.add_argument("--kb-host", default="127.0.0.1", help="KB host")
    parser.add_argument("--kb-port", type=int, default=3333, help="KB port")
    parser.add_argument("--timeout", type=float, default=2.0, help="KB query timeout in seconds")
    
    args = parser.parse_args()
    
    project = args.project or get_project_name()
    branch = get_git_branch()
    
    # 1. Check connection to KB
    status = check_kb_health(host=args.kb_host, port=args.kb_port, timeout=args.timeout)
    
    if status["success"]:
        # Healthy retrieval from KB
        capsule = build_capsule_from_kb(status["data"], project, branch)
        result = {
            "degraded": False,
            "source": "knowledge_base",
            "capsule": capsule
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)
    else:
        # Check if it was connection refused
        if status["conn_refused"]:
            try:
                headroom_results = await query_headroom(args.db_path, args.query or project, args.user_id)
                capsule = build_capsule_from_headroom(headroom_results, project, branch)
                result = {
                    "degraded": True,
                    "source": "headroom_memory",
                    "capsule": capsule
                }
                print(json.dumps(result, indent=2))
                sys.exit(0)
            except Exception as e:
                print(f"Error querying headroom fallback: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Latency / Timeout or other error -> "never on latency"
            print(f"Error: Knowledge Base query failed but did not refuse connection (timeout or other error). Fallback is gated. Error: {status['error']}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
