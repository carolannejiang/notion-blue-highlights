#!/usr/bin/env python3
"""Incrementally sync highlighted text of one color from Notion into a Notion database.

Scans pages edited since the last run, extracts rich text whose color matches
"color" in config.json (default blue_background), plus whole blocks of that
color, and upserts rows into the database keyed by block id + span index. Rows whose highlight
disappeared from a rescanned page are marked Removed.

Config: config.json (next to this file)  {"token": "...", "database_id": "...", "color": "..."}
State:  state.json  (next to this file)  {"last_sync": "<iso datetime>"}

Usage:
  sync.py                        incremental sync
  sync.py --create-db PAGE_ID    create the target database under PAGE_ID and
                                 write its id into config.json
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
OVERLAP = timedelta(minutes=10)  # rescan window to survive clock skew / missed runs
MAX_DEPTH = 10
DEFAULT_COLOR = "blue_background"
COLORS = {f"{c}_background" for c in
          ("gray", "brown", "orange", "yellow", "green", "blue", "purple", "pink", "red")}


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def request(token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(4):
        req = urllib.request.Request(
            API + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            time.sleep(0.34)  # stay under Notion's ~3 req/s limit
            return result
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After", "2")))
                continue
            if e.code >= 500 and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"giving up on {method} {path}")


def paginate(token, method, path, body=None, key="results"):
    cursor = None
    while True:
        b = dict(body or {})
        q = ""
        if cursor:
            if method == "GET":
                q = f"&start_cursor={cursor}" if "?" in path else f"?start_cursor={cursor}"
            else:
                b["start_cursor"] = cursor
        result = request(token, method, path + q, b if method != "GET" else None)
        yield from result.get(key, [])
        if not result.get("has_more"):
            return
        cursor = result["next_cursor"]


def plain(rich_list):
    return "".join(r.get("plain_text", "") for r in rich_list)


def block_highlights(block, color):
    """Return the text runs highlighted in `color` in one block, in document order."""
    btype = block["type"]
    obj = block.get(btype) or {}
    rich_lists = obj.get("cells", []) if btype == "table_row" else (
        [obj["rich_text"]] if isinstance(obj.get("rich_text"), list) else []
    )
    found = []
    if obj.get("color") == color and rich_lists:
        text = " ".join(filter(None, (plain(rl).strip() for rl in rich_lists)))
        if text:
            found.append(text)
    else:
        for rl in rich_lists:
            run = ""
            for seg in rl:
                if seg.get("annotations", {}).get("color") == color:
                    run += seg.get("plain_text", "")
                elif run:
                    found.append(run.strip())
                    run = ""
            if run.strip():
                found.append(run.strip())
    return [t for t in found if t]


def scan_page(token, page_id, color):
    """Walk a page's block tree; return {key: text} of highlights in `color`."""
    highlights = {}

    def walk(block_id, depth):
        if depth > MAX_DEPTH:
            return
        for block in paginate(token, "GET", f"/blocks/{block_id}/children?page_size=100"):
            for i, text in enumerate(block_highlights(block, color)):
                highlights[f"{block['id']}#{i}"] = text
            if block.get("has_children") and block["type"] not in ("child_page", "child_database"):
                walk(block["id"], depth + 1)

    walk(page_id, 0)
    return highlights


def existing_rows(token, database_id, page_url):
    rows = {}
    body = {"filter": {"property": "Source page", "url": {"equals": page_url}}, "page_size": 100}
    for row in paginate(token, "POST", f"/databases/{database_id}/query", body):
        props = row["properties"]
        key = plain(props.get("Block ID", {}).get("rich_text", []))
        if key:
            rows[key] = {
                "id": row["id"],
                "text": plain(props.get("Note", {}).get("rich_text", [])),
                "status": (props.get("Status", {}).get("select") or {}).get("name"),
            }
    return rows


def row_properties(text, key, page_url, page_id, status, today):
    snippet = text[:80] + "…" if len(text) > 80 else text
    return {
        "Highlight": {"title": [{"text": {"content": snippet}}]},
        "Note": {"rich_text": [{"text": {"content": text[:2000]}}]},
        "Source page": {"url": page_url},
        "Page": {"rich_text": [{"mention": {"page": {"id": page_id}}}]},
        "Block ID": {"rich_text": [{"text": {"content": key}}]},
        "Status": {"select": {"name": status}},
        "Last seen": {"date": {"start": today}},
    }


def sync_page(token, database_id, page, color):
    page_url = page["url"]
    found = scan_page(token, page["id"], color)
    rows = existing_rows(token, database_id, page_url)
    if not found and not rows:
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    changes = 0
    for key, text in found.items():
        row = rows.pop(key, None)
        props = row_properties(text, key, page_url, page["id"], "Active", today)
        if row is None:
            request(token, "POST", "/pages", {"parent": {"database_id": database_id}, "properties": props})
            changes += 1
        elif row["text"] != text or row["status"] != "Active":
            request(token, "PATCH", f"/pages/{row['id']}", {"properties": props})
            changes += 1
    for row in rows.values():  # previously recorded on this page, no longer highlighted
        if row["status"] != "Removed":
            request(token, "PATCH", f"/pages/{row['id']}", {"properties": {"Status": {"select": {"name": "Removed"}}}})
            changes += 1
    return changes


DB_PROPERTIES = {
    "Highlight": {"title": {}},
    "Note": {"rich_text": {}},
    "Page": {"rich_text": {}},
    "Source page": {"url": {}},
    "Block ID": {"rich_text": {}},
    "Status": {"select": {"options": [{"name": "Active", "color": "green"}, {"name": "Removed", "color": "gray"}]}},
    "Last seen": {"date": {}},
    "Captured": {"created_time": {}},
}


def create_db(token, config, parent_page_id):
    """Create the highlights database under a page and save its id to config.json."""
    db = request(token, "POST", "/databases", {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"text": {"content": "Highlights"}}],
        "properties": DB_PROPERTIES,
    })
    config["database_id"] = db["id"]
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"created database {db['url']}\nsaved database_id to {CONFIG_PATH}")


def main():
    config = load_json(CONFIG_PATH, {})
    token, database_id = config.get("token", ""), config.get("database_id", "")
    if not token or token.startswith("PASTE"):
        print("config.json has no token yet; nothing to do")
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--create-db":
        create_db(token, config, sys.argv[2].replace("-", ""))
        return
    if not database_id or database_id.startswith("PASTE"):
        print("config.json has no database_id; run: sync.py --create-db <parent page id>")
        return
    color = config.get("color", DEFAULT_COLOR)
    if color not in COLORS:
        print(f"config.json: unknown color {color!r}; choose one of {sorted(COLORS)}")
        return
    state = load_json(STATE_PATH, {})
    since = None
    if state.get("last_sync"):
        since = datetime.fromisoformat(state["last_sync"]) - OVERLAP
    run_started = datetime.now(timezone.utc)
    db_id_plain = database_id.replace("-", "")
    exclude = {p.replace("-", "") for p in config.get("exclude_pages", [])}

    scanned = changes = 0
    body = {
        "filter": {"value": "page", "property": "object"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        "page_size": 100,
    }
    for page in paginate(token, "POST", "/search", body):
        edited = datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00"))
        if since and edited < since:
            break  # results are newest-first; everything after this is older
        parent = page.get("parent", {})
        if parent.get("database_id", "").replace("-", "") == db_id_plain:
            continue  # skip the highlight rows themselves
        if page["id"].replace("-", "") in exclude:
            continue
        try:
            changes += sync_page(token, database_id, page, color)
            scanned += 1
        except Exception as e:  # noqa: BLE001 - keep going past a bad page
            print(f"error on {page.get('url')}: {e}", file=sys.stderr)

    STATE_PATH.write_text(json.dumps({"last_sync": run_started.isoformat()}))
    print(f"{run_started.isoformat()} scanned {scanned} pages, {changes} row changes")


if __name__ == "__main__":
    main()
