"""Run state: which Gmail messages are done, and every Salesforce write (with the
old value) so any run can be reviewed and undone."""
import json
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(__file__).resolve().parents[2] / "state"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(name, rec):
    STATE.mkdir(exist_ok=True)
    with (STATE / name).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read(name):
    p = STATE / name
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def is_processed(message_id):
    return any(r["message_id"] == message_id for r in _read("processed.jsonl"))


def mark_processed(message_id, email, category, run_id):
    _append("processed.jsonl", {"at": _now(), "run_id": run_id, "message_id": message_id,
                                "email": email, "category": category})


def log_write(run_id, object_name, record_id, field, old, new):
    _append("writes.jsonl", {"at": _now(), "run_id": run_id, "object": object_name,
                             "record_id": record_id, "field": field, "old": old, "new": new})


def undo_list(run_id):
    """The writes of one run, newest first, with the value to restore."""
    rows = [r for r in _read("writes.jsonl") if r["run_id"] == run_id]
    return [{"object": r["object"], "record_id": r["record_id"], "field": r["field"],
             "restore_to": r["old"]} for r in reversed(rows)]
