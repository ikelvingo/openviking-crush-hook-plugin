"""OpenViking recall hook for Crush (PreToolUse).

Injects bounded OpenViking recall into the tool result via the hook
`context` field whenever the current user question has not been recalled
yet. Query is the latest user message of the current session read from
crush.db, so it reproduces the "recall before answering" pattern as closely
as PreToolUse allows. Never blocks and never auto-approves.
"""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ov_common import http, last_user_message, load_identity, log, state_get, state_set

RECALL_PATH = "/api/v1/search/recall"
MIN_INTERVAL = float(os.environ.get("OV_RECALL_MIN_INTERVAL", "25"))
MAX_CHARS = int(os.environ.get("OV_RECALL_MAX_CHARS", "1600"))
RECALL_LIMIT = int(os.environ.get("OV_RECALL_LIMIT", "6"))
MIN_QUERY_LEN = int(os.environ.get("OV_RECALL_MIN_QUERY_LEN", "3"))


def main():
    session_id = os.environ.get("CRUSH_SESSION_ID", "")
    if not session_id:
        print("{}")
        return 0

    query = last_user_message(session_id).strip()
    if len(query) < MIN_QUERY_LEN:
        print("{}")
        return 0

    qhash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    st = state_get(session_id, "recall")
    now = time.time()
    if st.get("last_query_hash") == qhash:
        # already injected for this question
        print("{}")
        return 0
    if now - st.get("last_at", 0) < MIN_INTERVAL:
        print("{}")
        return 0

    ident = load_identity()
    body = {
        "query": query,
        "quotas": {
            "events": RECALL_LIMIT,
            "entities": RECALL_LIMIT,
            "preferences": 3,
            "experiences": 0,
        },
        "max_chars": MAX_CHARS,
        "min_score": 0.35,
        "render": True,
        "peer_scope": "actor",
    }
    res = http("POST", RECALL_PATH, ident, body, timeout=8)
    rendered = None
    if res and isinstance(res, dict) and res.get("status") == "ok":
        rendered = (res.get("result") or {}).get("rendered")

    state_set(session_id, "recall", {"last_at": now, "last_query_hash": qhash})
    if not rendered:
        print("{}")
        return 0

    block = (
        "<openviking-context>\n"
        "Relevant memory from OpenViking (peer: %s). Use the ov CLI to read/expand URIs if needed.\n"
        "%s\n"
        "</openviking-context>" % (ident["peer"], rendered[: MAX_CHARS * 2])
    )
    log("recall injected session=%s chars=%d" % (session_id, len(block)))
    print(json.dumps({"context": block}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
