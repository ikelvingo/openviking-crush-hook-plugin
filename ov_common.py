"""Shared helpers for OpenViking Crush hooks.

Identity resolution (env wins over conf file, matching the omp package):
  OPENVIKING_URL / OPENVIKING_BASE_URL      -> server url
  OPENVIKING_API_KEY / OPENVIKING_BEARER_TOKEN -> api key
  OPENVIKING_PEER_ID                        -> actor peer id
  OPENVIKING_CLI_CONFIG_FILE                -> override conf file
Default conf: ~/.openviking/ovcli-crush.conf, fallback ~/.openviking/ovcli.conf
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from urllib.parse import quote

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HOOKS_DIR, "state")
LOG_PATH = os.path.join(STATE_DIR, "ov_hooks.log")


def log(msg):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def load_identity():
    conf = {}
    candidates = [
        os.environ.get("OPENVIKING_CLI_CONFIG_FILE", ""),
        os.path.join(os.path.expanduser("~"), ".openviking", "ovcli-crush.conf"),
        os.path.join(os.path.expanduser("~"), ".openviking", "ovcli.conf"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                conf = json.load(open(p, encoding="utf-8"))
                break
            except Exception:
                continue
    url = (
        os.environ.get("OPENVIKING_URL")
        or os.environ.get("OPENVIKING_BASE_URL")
        or conf.get("url", "")
    )
    key = (
        os.environ.get("OPENVIKING_API_KEY")
        or os.environ.get("OPENVIKING_BEARER_TOKEN")
        or conf.get("api_key", "")
    )
    peer = os.environ.get("OPENVIKING_PEER_ID") or conf.get("actor_peer_id") or "cli"
    return {"url": url.rstrip("/"), "api_key": key, "peer": peer}


def http(method, path, ident, body=None, timeout=8):
    """Call the OpenViking REST API. Returns parsed JSON envelope or None."""
    url = ident["url"] + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if ident["api_key"]:
        req.add_header("Authorization", "Bearer " + ident["api_key"])
    if ident["peer"]:
        req.add_header("X-OpenViking-Actor-Peer", ident["peer"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        log("http %s %s -> %s: %s" % (method, path, e.code, e.read().decode("utf-8", "replace")[:200]))
        return None
    except Exception as e:
        log("http %s %s failed: %s" % (method, path, e))
        return None


def state_get(session_id, name):
    p = os.path.join(STATE_DIR, "%s_%s.json" % (name, session_id))
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def state_set(session_id, name, obj):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, "%s_%s.json" % (name, session_id)), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception as e:
        log("state write failed: %s" % e)


def open_crush_db():
    db = os.path.join(os.path.expanduser("~"), ".crush", "crush.db")
    if not os.path.exists(db):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % quote(db), uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        return con
    except Exception as e:
        log("crush.db open failed: %s" % e)
        return None


def extract_text(parts_json):
    """Extract plain text from a crush.db message parts blob."""
    try:
        parts = json.loads(parts_json) if isinstance(parts_json, str) else parts_json
    except Exception:
        return ""
    if not isinstance(parts, list):
        return ""
    out = []
    for p in parts:
        if not isinstance(p, dict) or p.get("type") != "text":
            continue
        d = p.get("data")
        t = ""
        if isinstance(d, dict):
            t = d.get("text") or d.get("content") or ""
        elif isinstance(d, str):
            t = d
        if t:
            out.append(t)
    return "\n".join(out)


def last_user_message(session_id):
    con = open_crush_db()
    if con is None:
        return ""
    try:
        row = con.execute(
            "SELECT parts FROM messages WHERE session_id=? AND role='user'"
            " AND is_summary_message=0 ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return extract_text(row["parts"]) if row else ""
    except Exception as e:
        log("last_user_message failed: %s" % e)
        return ""
    finally:
        con.close()


def ov_session_id(crush_session_id):
    return "crush-" + crush_session_id
