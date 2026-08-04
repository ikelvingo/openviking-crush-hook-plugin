"""OpenViking capture hook for Crush (PreToolUse).

Approximates "capture after every turn": on each tool call it diffs the
current crush.db session transcript against a per-session watermark and
uploads new user/assistant text turns to the OpenViking session, then
commits (archiving + memory extraction) once pending tokens cross the
threshold. Never blocks.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ov_common import (
    extract_text,
    http,
    load_identity,
    log,
    open_crush_db,
    ov_session_id,
    state_get,
    state_set,
)
from urllib.parse import quote

COMMIT_THRESHOLD = int(os.environ.get("OV_COMMIT_THRESHOLD", "20000"))
KEEP_RECENT = int(os.environ.get("OV_COMMIT_KEEP_RECENT", "20"))
MAX_MSG = int(os.environ.get("OV_CAPTURE_MAX_MSG", "30000"))


def main():
    session_id = os.environ.get("CRUSH_SESSION_ID", "")
    if not session_id:
        print("{}")
        return 0

    ident = load_identity()
    if not ident["url"]:
        print("{}")
        return 0

    ov_id = ov_session_id(session_id)
    http("POST", "/api/v1/sessions", ident, {"session_id": ov_id}, timeout=8)

    con = open_crush_db()
    if con is None:
        print("{}")
        return 0

    st = state_get(session_id, "capture")
    since = st.get("since_id", 0)
    try:
        rows = con.execute(
            "SELECT id, role, parts FROM messages WHERE session_id=? AND id>?"
            " AND is_summary_message=0 ORDER BY id",
            (session_id, since),
        ).fetchall()
    except Exception as e:
        log("capture select failed: %s" % e)
        return 0
    finally:
        con.close()

    msgs = []
    for r in rows:
        role = r["role"]
        if role not in ("user", "assistant"):
            continue
        text = extract_text(r["parts"]).strip()
        if not text:
            continue
        msgs.append({"role": role, "content": text[:MAX_MSG]})

    if msgs:
        ok = True
        for m in msgs:
            res = http(
                "POST",
                "/api/v1/sessions/%s/messages" % quote(ov_id),
                ident,
                m,
                timeout=8,
            )
            if not res or res.get("status") != "ok":
                ok = False
                log("capture message failed session=%s role=%s" % (session_id, m["role"]))
                break
        if ok:
            state_set(session_id, "capture", {"since_id": rows[-1]["id"]})
            log("captured %d messages session=%s" % (len(msgs), session_id))

    meta = http("GET", "/api/v1/sessions/%s" % quote(ov_id), ident, timeout=6)
    pending = 0
    if meta and isinstance(meta, dict):
        pending = int((meta.get("result") or {}).get("pending_tokens") or 0)
    if pending >= COMMIT_THRESHOLD:
        http(
            "POST",
            "/api/v1/sessions/%s/commit" % quote(ov_id),
            ident,
            {"keep_recent_count": KEEP_RECENT},
            timeout=25,
        )
        log("committed session=%s pending=%d" % (session_id, pending))

    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
