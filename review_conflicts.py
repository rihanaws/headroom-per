#!/usr/bin/env python3
"""Operator CLI for manual-review.json conflict resolution.

Per Decision #14: no server endpoint. Applies/undoes deactivation directly
against the knowledge-base SQLite db via the existing is_active flag.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

MANUAL_REVIEW_PATH = Path(__file__).parent / "manual-review.json"
KB_DB_PATH = Path("/Users/rihan/all-coding-project/knowledge-base/knowledge_base.sqlite")

ACTIONS = ["deactivate", "keep", "dismiss"]


def load_entries():
    if not MANUAL_REVIEW_PATH.exists():
        return []
    with open(MANUAL_REVIEW_PATH) as f:
        return json.load(f)


def save_entries(entries):
    with open(MANUAL_REVIEW_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def find_previous_row(conn, entry):
    rows = conn.execute(
        "SELECT id FROM observations WHERE entity_name = ? AND content = ? AND is_active = 1",
        (entry["project"], entry["previous"]["content"]),
    ).fetchall()
    return rows


def find_deactivated_row(conn, entry):
    rows = conn.execute(
        "SELECT id FROM observations WHERE entity_name = ? AND content = ? AND is_active = 0",
        (entry["project"], entry["previous"]["content"]),
    ).fetchall()
    return rows


def print_entry(idx, entry):
    print(f"\n[{idx}] source #{entry['source_id']} project={entry['project']} detected_at={entry['detected_at']}")
    print(f"    previous ({entry['previous']['written_at']}): {entry['previous']['content'][:100]}")
    print(f"    incoming: {entry['incoming']['content'][:100]}")
    print(f"    status: {entry.get('resolution', {}).get('action', 'pending')}")


def cmd_list(args):
    entries = load_entries()
    if not entries:
        print("No entries in manual-review.json.")
        return
    pending = [e for e in entries if "resolution" not in e]
    resolved = [e for e in entries if "resolution" in e]
    print(f"{len(pending)} pending, {len(resolved)} resolved.")
    for i, e in enumerate(entries):
        print_entry(i, e)


def cmd_resolve(args):
    entries = load_entries()
    if args.index < 0 or args.index >= len(entries):
        print(f"Error: index {args.index} out of range (0..{len(entries)-1}).", file=sys.stderr)
        sys.exit(1)
    entry = entries[args.index]
    if "resolution" in entry:
        print(f"Error: entry {args.index} already resolved with action '{entry['resolution']['action']}'. Use --restore to undo first.", file=sys.stderr)
        sys.exit(1)

    if args.action == "deactivate":
        conn = sqlite3.connect(KB_DB_PATH)
        try:
            rows = find_previous_row(conn, entry)
            if len(rows) == 0:
                print("Error: no matching active row found for previous content. Refusing to guess.", file=sys.stderr)
                sys.exit(1)
            if len(rows) > 1:
                print(f"Error: {len(rows)} ambiguous matching rows found. Refusing to guess — resolve manually.", file=sys.stderr)
                sys.exit(1)
            row_id = rows[0][0]
            conn.execute("UPDATE observations SET is_active = 0 WHERE id = ?", (row_id,))
            conn.commit()
            entry["resolution"] = {"action": "deactivate", "kb_row_id": row_id}
            print(f"Deactivated observations.id={row_id}.")
        finally:
            conn.close()
    elif args.action == "keep":
        entry["resolution"] = {"action": "keep"}
        print("Marked resolved: keep both (no KB mutation).")
    elif args.action == "dismiss":
        entry["resolution"] = {"action": "dismiss"}
        print("Marked resolved: dismissed (no KB mutation).")

    save_entries(entries)


def cmd_restore(args):
    entries = load_entries()
    if args.index < 0 or args.index >= len(entries):
        print(f"Error: index {args.index} out of range (0..{len(entries)-1}).", file=sys.stderr)
        sys.exit(1)
    entry = entries[args.index]
    resolution = entry.get("resolution")
    if not resolution:
        print(f"Error: entry {args.index} has no resolution to restore.", file=sys.stderr)
        sys.exit(1)

    if resolution["action"] == "deactivate":
        row_id = resolution.get("kb_row_id")
        conn = sqlite3.connect(KB_DB_PATH)
        try:
            conn.execute("UPDATE observations SET is_active = 1 WHERE id = ?", (row_id,))
            conn.commit()
            print(f"Restored observations.id={row_id} to is_active=1.")
        finally:
            conn.close()
    else:
        print(f"Resolution was '{resolution['action']}' (no KB mutation to undo).")

    del entry["resolution"]
    save_entries(entries)


def main():
    parser = argparse.ArgumentParser(description="Resolve manual-review.json conflicts.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List pending and resolved entries.")

    p_resolve = sub.add_parser("resolve", help="Resolve an entry by index.")
    p_resolve.add_argument("index", type=int, help="Entry index from `list`.")
    p_resolve.add_argument("action", choices=ACTIONS, help="deactivate previous / keep both / dismiss.")

    p_restore = sub.add_parser("restore", help="Undo a resolution by index (--restore).")
    p_restore.add_argument("index", type=int, help="Entry index from `list`.")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "resolve":
        cmd_resolve(args)
    elif args.command == "restore":
        cmd_restore(args)


if __name__ == "__main__":
    main()
