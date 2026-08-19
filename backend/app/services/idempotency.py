"""
Idempotency key computation, shared by the planning and execution endpoints.

The key is a pure function of (tool, params): two actions that call the
same tool with the same parameters get the same key, regardless of which
Plan they belong to. That is what lets the execution endpoint detect "this
exact action was already executed under an earlier, regenerated plan" and
skip dispatching it again (see models.Action.idempotency_key and
SEQUENCES.md diagram 3).

plan_id is deliberately NOT part of the key. An earlier design note
described the key as hash(plan_id, tool, normalized_params); that would
make every regenerated plan produce fresh keys and defeat the whole point
of this check, since each resubmission creates a brand new Plan row with a
new id. This implementation intentionally corrects that.
"""

import hashlib
import json
from typing import Any


def compute_idempotency_key(tool: str, params: dict[str, Any]) -> str:
    """Deterministic key: same tool + same params (any key order) -> same
    key. Different tool or different params -> different key."""
    normalized = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest_input = f"{tool}:{normalized}"
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
