"""validation_stamp.py -- the read side of the ``require_validated_output`` completion
gate (OPEN_ITEMS item 18 in career-workflow: a worker completing a sweep with only a
``summary`` key and no ``metadata`` at all, bypassing validate_output entirely).

The WRITE side deliberately lives outside this repo, in each profile's own
validate-style MCP tool (e.g. career-workflow's ``scripts/mcp_sweep_validate.py``,
``_handle_validate_output``) -- not here, and not by hooking the generic MCP
dispatch path in ``tools/mcp_tool_handlers.py``. That would make the stamp
mechanism "free" for every profile's validate tool automatically, but at the cost
of a change to code every profile's every MCP call passes through, for a gate only
one profile currently opts into. A profile's own validate tool already knows
exactly when it has produced a real verdict; writing the stamp there is a few
lines, keeps the core dispatch path untouched, and any profile can adopt the same
convention by writing to the same path -- no import of this module required (it's
a plain JSON file contract, not a shared library dependency), and no hermes-agent
dependency added to a profile-local, ideally-portable stdio server.

Stamp file: STAMP_DIR / <task_id>.json =
    {"run_id": <int|null>, "valid": <bool>, "candidate_hash": "<sha256 hex>"}

``candidate_hash`` ties the stamp to the EXACT object that was validated -- see
``canonical_hash`` -- so a worker cannot validate one (correct) object and then
complete with a different one. ``run_id`` ties it to the CURRENT dispatcher run --
a stamp from a previous, failed attempt at the same task does not count.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

STAMP_DIR = Path.home() / ".hermes" / "kanban" / "validation_stamps"


def canonical_hash(candidate: Any) -> str:
    """Sha256 hex of ``candidate``'s canonical JSON. Both sides of the stamp
    contract (the validate tool that writes it, kanban_complete's gate that
    reads it) must compute this identically -- sort_keys + compact separators,
    nothing else, so it never depends on either side's json.dumps defaults."""
    canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_stamp(task_id: str) -> Optional[dict]:
    """The stamp for ``task_id``, or None if absent/corrupt (corrupt is treated
    as absent -- the gate fails closed either way, never crashes)."""
    path = STAMP_DIR / f"{task_id}.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        stamp = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return stamp if isinstance(stamp, dict) else None


def check_validation_gate(task_id: str, run_id: Optional[int], metadata: Any) -> Optional[str]:
    """None when the gate is satisfied; else a worker-facing message naming
    exactly what's missing/mismatched, safe to return straight from a
    tool_error (never raises)."""
    stamp = read_stamp(task_id)
    if stamp is None:
        return (
            "require_validated_output is set on this task, but no validate_output stamp "
            "was found. Call your profile's validate_output tool with this exact metadata "
            "object and confirm it returns valid:true before calling kanban_complete."
        )
    if stamp.get("run_id") != run_id:
        return (
            "require_validated_output is set on this task, but the validate_output stamp "
            "on file is from a different run (a previous attempt). Call validate_output "
            "again in THIS run with this exact metadata object before calling kanban_complete."
        )
    if stamp.get("valid") is not True:
        return (
            "require_validated_output is set on this task, but the last validate_output "
            "call in this run reported valid:false. Fix the reported errors, call "
            "validate_output again, and confirm valid:true before calling kanban_complete."
        )
    if stamp.get("candidate_hash") != canonical_hash(metadata):
        return (
            "require_validated_output is set on this task, but the metadata you're "
            "completing with does not match the object validate_output last approved "
            "(hash mismatch). Call validate_output again with THIS EXACT metadata object, "
            "confirm valid:true, then call kanban_complete with the same object unmodified."
        )
    return None
