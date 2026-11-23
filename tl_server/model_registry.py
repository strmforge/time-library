"""Model sources and who does which job.

A source is an address + a protocol + a key + a default model. Jobs ("slots")
are not wired to any source in code: the owner assigns a main and an optional
backup model to each job, and can change that at any time. A model is only
accepted for a job after one real call to it has succeeded.

Keys never go into the database. They live in their own file in the data
directory, readable by the server's user only, and are never sent to clients.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from . import model_client
from .errors import ApiError
from .model_client import ModelError
from .store import Store

SLOTS = ("import", "daily", "reflect")
ROLES = ("main", "backup")
# A remote endpoint answers in seconds; a model on the NAS's own processor reads
# a long stretch of dialogue in minutes.
REMOTE_CALL_TIMEOUT = 240
BUILTIN_CALL_TIMEOUT = 1800
BUILTIN_PROBE_TIMEOUT = 600

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  protocol TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  models_cache TEXT NOT NULL DEFAULT '[]',
  tested_ok INTEGER NOT NULL DEFAULT 0,
  tested_at REAL,
  last_error_reason TEXT NOT NULL DEFAULT '',
  last_error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reported_levels (
  model TEXT PRIMARY KEY,
  levels TEXT NOT NULL,
  default_level TEXT NOT NULL DEFAULT '',
  reported_by TEXT NOT NULL DEFAULT '',
  reported_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS model_slots (
  slot TEXT PRIMARY KEY,
  main_source INTEGER,
  main_model TEXT NOT NULL DEFAULT '',
  backup_source INTEGER,
  backup_model TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL
);
"""


def _field(value: Any, name: str, *, min_len: int = 0, max_len: int) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "invalid_field", f"{name} must be a string")
    value = value.strip()
    if not min_len <= len(value) <= max_len:
        raise ApiError(400, "invalid_field", f"{name} length must be {min_len}..{max_len}")
    return value


class ModelRegistry:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._keys_path = store.data_dir / "model_keys.json"
        self.local = None  # the built-in local model, when the server has one
        with store._lock:
            store._db.executescript(SCHEMA)
            columns = {row["name"] for row in store._db.execute("PRAGMA table_info(model_sources)")}
            if "builtin" not in columns:
                store._db.execute("ALTER TABLE model_sources ADD COLUMN builtin INTEGER NOT NULL DEFAULT 0")
            if "model_levels" not in columns:
                # The thinking levels each model reports in the endpoint's model list.
                store._db.execute("ALTER TABLE model_sources ADD COLUMN model_levels TEXT NOT NULL DEFAULT '{}'")
            slot_columns = {row["name"] for row in store._db.execute("PRAGMA table_info(model_slots)")}
            if "effort" not in slot_columns:
                # How much thinking to ask for on this job: '' = the model's default.
                store._db.execute("ALTER TABLE model_slots ADD COLUMN effort TEXT NOT NULL DEFAULT ''")

    # ---- keys --------------------------------------------------------------

    def _read_keys(self) -> dict[str, str]:
        try:
            data = json.loads(self._keys_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _write_keys(self, keys: dict[str, str]) -> None:
        tmp = self._keys_path.with_name(".model_keys.json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(keys, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._keys_path)

    def key(self, source_id: int) -> str:
        self._row(source_id)
        with self._store._lock:
            return self._read_keys().get(str(source_id), "")

    # ---- reading -----------------------------------------------------------

    def _row(self, source_id: int):
        with self._store._lock:
            row = self._store._db.execute("SELECT * FROM model_sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise ApiError(404, "source_not_found")
        return row

    def _public(self, row, keys: dict[str, str]) -> dict[str, Any]:
        key = keys.get(str(row["id"]), "")
        return {
            "id": row["id"],
            "name": row["name"],
            "base_url": row["base_url"],
            "protocol": row["protocol"],
            "model": row["model"],
            "models": json.loads(row["models_cache"]),
            "levels": json.loads(row["model_levels"]) if "model_levels" in row.keys() else {},
            "key_set": bool(key),
            "key_hint": ("••••" + key[-4:]) if len(key) >= 8 else ("••••" if key else ""),
            "builtin": bool(row["builtin"]),
            "tested_ok": bool(row["tested_ok"]),
            "tested_at": row["tested_at"],
            "last_error_reason": row["last_error_reason"],
            "last_error": row["last_error"],
        }

    def report_levels(self, models: Any, agent: Any, device: str) -> dict[str, int]:
        """Thinking levels from a model catalog an agent keeps (its provider's official list)."""
        if not isinstance(models, list) or len(models) > 500:
            raise ApiError(400, "invalid_field", "models must be a list of at most 500 items")
        rows = []
        for index, item in enumerate(models):
            if not isinstance(item, Mapping):
                raise ApiError(400, "invalid_field", f"models[{index}] must be an object")
            model = _field(item.get("id"), f"models[{index}].id", min_len=1, max_len=128)
            levels = item.get("levels") or []
            if not isinstance(levels, list) or len(levels) > 16 or not all(
                isinstance(level, str) and model_client.EFFORT_PATTERN.match(level) for level in levels
            ):
                raise ApiError(400, "invalid_field", f"models[{index}].levels must be a list of level words")
            default = item.get("default") or ""
            if not isinstance(default, str) or (default and not model_client.EFFORT_PATTERN.match(default)):
                raise ApiError(400, "invalid_field", f"models[{index}].default must be a level word")
            who = f"{agent.strip()[:60]} @ {device}" if isinstance(agent, str) and agent.strip() else device
            rows.append((model, json.dumps(levels), default, who, self._store._clock()))
        with self._store._tx() as db:
            db.executemany(
                """
                INSERT INTO reported_levels(model, levels, default_level, reported_by, reported_at) VALUES(?,?,?,?,?)
                ON CONFLICT(model) DO UPDATE SET levels=excluded.levels, default_level=excluded.default_level,
                    reported_by=excluded.reported_by, reported_at=excluded.reported_at
                """,
                rows,
            )
        return {"recorded": len(rows)}

    def _levels_for(self, row, reported: dict[str, Any]) -> dict[str, Any]:
        """Per model of a source: the levels its endpoint reports, else what an agent's catalog says."""
        own = json.loads(row["model_levels"]) if "model_levels" in row.keys() else {}
        merged: dict[str, Any] = {}
        for model in {*json.loads(row["models_cache"]), *([row["model"]] if row["model"] else [])}:
            if model in own:
                merged[model] = {**own[model], "from": "endpoint"}
                continue
            # A relay may name a model with a prefix ("vendor/model"): fall back to the last part.
            found = reported.get(model) or reported.get(model.rsplit("/", 1)[-1])
            if found:
                merged[model] = found
        return merged

    def listing(self) -> dict[str, Any]:
        with self._store._lock:
            rows = self._store._db.execute("SELECT * FROM model_sources ORDER BY id").fetchall()
            slot_rows = {row["slot"]: row for row in self._store._db.execute("SELECT * FROM model_slots")}
            reported = {
                row["model"]: {"levels": json.loads(row["levels"]), "default": row["default_level"], "from": row["reported_by"]}
                for row in self._store._db.execute("SELECT * FROM reported_levels")
            }
            keys = self._read_keys()
        slots = {}
        for slot in SLOTS:
            row = slot_rows.get(slot)
            slots[slot] = {
                role: ({"source_id": row[f"{role}_source"], "model": row[f"{role}_model"]} if row and row[f"{role}_source"] else None)
                for role in ROLES
            }
            slots[slot]["effort"] = row["effort"] if row and "effort" in row.keys() else ""
        sources = []
        for row in rows:
            public = self._public(row, keys)
            public["levels"] = self._levels_for(row, reported)
            sources.append(public)
        return {
            "sources": sources,
            "slots": slots,
            "protocols": list(model_client.PROTOCOLS),
        }

    # ---- sources -----------------------------------------------------------

    def _validated(self, fields: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if creating or "name" in fields:
            out["name"] = _field(fields.get("name"), "name", min_len=1, max_len=64)
        if creating or "base_url" in fields:
            url = _field(fields.get("base_url"), "base_url", min_len=8, max_len=512).rstrip("/")
            if not url.startswith(("http://", "https://")):
                raise ApiError(400, "invalid_field", "base_url must start with http:// or https://")
            out["base_url"] = url
        if creating or "protocol" in fields:
            protocol = fields.get("protocol")
            if protocol not in model_client.PROTOCOLS:
                raise ApiError(400, "invalid_field", "protocol must be one of: " + ", ".join(model_client.PROTOCOLS))
            out["protocol"] = protocol
        if "model" in fields:
            out["model"] = _field(fields.get("model"), "model", max_len=128)
        if "api_key" in fields:
            out["api_key"] = _field(fields.get("api_key"), "api_key", max_len=512)
        return out

    def create_source(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        values = self._validated(fields, creating=True)
        now = self._store._clock()
        with self._store._tx() as db:
            cursor = db.execute(
                "INSERT INTO model_sources(name, base_url, protocol, model, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (values["name"], values["base_url"], values["protocol"], values.get("model", ""), now, now),
            )
            source_id = cursor.lastrowid
            if values.get("api_key"):
                keys = self._read_keys()
                keys[str(source_id)] = values["api_key"]
                self._write_keys(keys)
        return self.source(source_id)

    def upsert_builtin(self, name: str, base_url: str, protocol: str, model: str) -> int:
        """Register (or refresh) the source that points at the server's own model."""
        now = self._store._clock()
        with self._store._tx() as db:
            row = db.execute("SELECT id FROM model_sources WHERE builtin=1").fetchone()
            if row is None:
                return db.execute(
                    "INSERT INTO model_sources(name, base_url, protocol, model, models_cache, builtin, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,1,?,?)",
                    (name, base_url, protocol, model, json.dumps([model]), now, now),
                ).lastrowid
            db.execute(
                "UPDATE model_sources SET base_url=?, protocol=?, model=?, models_cache=?, updated_at=? WHERE id=?",
                (base_url, protocol, model, json.dumps([model]), now, row["id"]),
            )
            return row["id"]

    def prepare(self, source_id: int) -> float:
        """Get a source ready for a call and say how long that call may take."""
        row = self._row(source_id)
        if not row["builtin"]:
            return REMOTE_CALL_TIMEOUT
        if self.local is not None:
            try:
                self.local.ensure_running()
            except Exception as error:
                raise ModelError(model_client.REASON_UNREACHABLE, f"the built-in model could not start: {error}") from None
        return BUILTIN_CALL_TIMEOUT

    def update_source(self, source_id: int, fields: Mapping[str, Any]) -> dict[str, Any]:
        row = self._row(source_id)
        if row["builtin"]:
            raise ApiError(409, "builtin_source", "the built-in model is managed from its own switch")
        values = self._validated(fields, creating=False)
        now = self._store._clock()
        with self._store._tx() as db:
            keys = self._read_keys()
            changed = any(key in values and values[key] != row[key] for key in ("base_url", "protocol", "model"))
            if "api_key" in values and values["api_key"] != keys.get(str(source_id), ""):
                changed = True
                if values["api_key"]:
                    keys[str(source_id)] = values["api_key"]
                else:
                    keys.pop(str(source_id), None)
                self._write_keys(keys)
            db.execute(
                "UPDATE model_sources SET name=?, base_url=?, protocol=?, model=?, updated_at=? WHERE id=?",
                (
                    values.get("name", row["name"]),
                    values.get("base_url", row["base_url"]),
                    values.get("protocol", row["protocol"]),
                    values.get("model", row["model"]),
                    now,
                    source_id,
                ),
            )
            if changed:
                # Anything that affects a call invalidates the last successful test.
                db.execute(
                    "UPDATE model_sources SET tested_ok=0, tested_at=NULL, last_error_reason='', last_error='' WHERE id=?",
                    (source_id,),
                )
            if any(key in values and values[key] != row[key] for key in ("base_url", "protocol")):
                db.execute("UPDATE model_sources SET models_cache='[]' WHERE id=?", (source_id,))
        return self.source(source_id)

    def delete_source(self, source_id: int, *, builtin_ok: bool = False) -> None:
        if self._row(source_id)["builtin"] and not builtin_ok:
            raise ApiError(409, "builtin_source", "the built-in model is managed from its own switch")
        now = self._store._clock()
        with self._store._tx() as db:
            db.execute("DELETE FROM model_sources WHERE id=?", (source_id,))
            for role in ROLES:
                db.execute(
                    f"UPDATE model_slots SET {role}_source=NULL, {role}_model='', updated_at=? WHERE {role}_source=?",
                    (now, source_id),
                )
            keys = self._read_keys()
            if keys.pop(str(source_id), None) is not None:
                self._write_keys(keys)

    def source(self, source_id: int) -> dict[str, Any]:
        row = self._row(source_id)
        with self._store._lock:
            return self._public(row, self._read_keys())

    # ---- calls that leave the server ----------------------------------------

    def fetch_models(self, source_id: int) -> dict[str, Any]:
        row = self._row(source_id)
        try:
            self.prepare(source_id)
            entries = model_client.list_models_detailed(row["base_url"], row["protocol"], self.key(source_id))
        except ModelError as error:
            raise ApiError(502, f"model_{error.reason}", error.message) from None
        models = [entry["id"] for entry in entries]
        levels = {
            entry["id"]: {"levels": entry["levels"], "default": entry["default_level"]}
            for entry in entries
            if entry["levels"] or entry["default_level"]
        }
        with self._store._tx() as db:
            db.execute(
                "UPDATE model_sources SET models_cache=?, model_levels=?, updated_at=? WHERE id=?",
                (json.dumps(models, ensure_ascii=False), json.dumps(levels, ensure_ascii=False), self._store._clock(), source_id),
            )
        return {"models": models, "levels": levels}

    def test_source(self, source_id: int, model: Any = None, effort: str = "") -> dict[str, Any]:
        """One real call with the source's protocol. Records the outcome when it
        is the source's own default model that was tested."""
        row = self._row(source_id)
        chosen = _field(model, "model", max_len=128) if model is not None else row["model"]
        if not chosen:
            raise ApiError(400, "model_required", "choose a model first")
        now = self._store._clock()
        try:
            self.prepare(source_id)
            outcome = model_client.probe(
                row["base_url"], row["protocol"], self.key(source_id), chosen,
                timeout=BUILTIN_PROBE_TIMEOUT if row["builtin"] else 60, effort=effort,
            )
            result = {"ok": True, "model": chosen, "latency_ms": outcome["latency_ms"]}
        except ModelError as error:
            result = {"ok": False, "model": chosen, "reason": error.reason, "message": error.message}
        if chosen == row["model"] and not effort:  # a refused level says nothing about the source itself
            with self._store._tx() as db:
                db.execute(
                    "UPDATE model_sources SET tested_ok=?, tested_at=?, last_error_reason=?, last_error=? WHERE id=?",
                    (1 if result["ok"] else 0, now, result.get("reason", ""), result.get("message", ""), source_id),
                )
        return result

    def note_failure(self, source_id: int, error: ModelError) -> None:
        """A job found this source not answering: show that, with the reason."""
        with self._store._tx() as db:
            db.execute(
                "UPDATE model_sources SET tested_ok=0, tested_at=?, last_error_reason=?, last_error=? WHERE id=?",
                (self._store._clock(), error.reason, error.message, source_id),
            )

    def note_success(self, source_id: int) -> None:
        """A job got an answer from a source that was marked as failing: it is back."""
        with self._store._tx() as db:
            db.execute(
                "UPDATE model_sources SET tested_ok=1, tested_at=?, last_error_reason='', last_error='' "
                "WHERE id=? AND last_error_reason != ''",
                (self._store._clock(), source_id),
            )

    # ---- jobs --------------------------------------------------------------

    def set_slot(self, slot: Any, role: Any, source_id: Any, model: Any) -> dict[str, Any]:
        if slot not in SLOTS:
            raise ApiError(400, "invalid_field", "slot must be one of: " + ", ".join(SLOTS))
        if role not in ROLES:
            raise ApiError(400, "invalid_field", "role must be main or backup")
        now = self._store._clock()
        if source_id is None:
            chosen_model = ""
        else:
            if isinstance(source_id, bool) or not isinstance(source_id, int):
                raise ApiError(400, "invalid_field", "source_id must be an integer or null")
            row = self._row(source_id)
            chosen_model = _field(model if model is not None else row["model"], "model", min_len=1, max_len=128)
            # Never hand a job to a model that has not answered one real call.
            outcome = self.test_source(source_id, chosen_model)
            if not outcome["ok"]:
                raise ApiError(422, f"model_{outcome['reason']}", outcome.get("message", ""))
        with self._store._tx() as db:
            db.execute("INSERT OR IGNORE INTO model_slots(slot, updated_at) VALUES(?, ?)", (slot, now))
            db.execute(
                f"UPDATE model_slots SET {role}_source=?, {role}_model=?, updated_at=? WHERE slot=?",
                (source_id, chosen_model, now, slot),
            )
        return self.listing()["slots"][slot]

    def set_effort(self, slot: Any, effort: Any) -> dict[str, Any]:
        if slot not in SLOTS:
            raise ApiError(400, "invalid_field", "slot must be one of: " + ", ".join(SLOTS))
        if not isinstance(effort, str) or (effort and not model_client.EFFORT_PATTERN.match(effort.strip())):
            raise ApiError(400, "invalid_field", "effort must be empty (the model's default) or the model's own word for a level")
        effort = effort.strip()
        with self._store._lock:
            row = self._store._db.execute("SELECT * FROM model_slots WHERE slot=?", (slot,)).fetchone()
        if effort and row is not None and row["main_source"]:
            # Like a model: a level is kept only once the model answered a real call with it.
            outcome = self.test_source(row["main_source"], row["main_model"], effort=effort)
            if not outcome["ok"]:
                raise ApiError(422, f"model_{outcome['reason']}", outcome.get("message", ""))
        with self._store._tx() as db:
            db.execute("INSERT OR IGNORE INTO model_slots(slot, updated_at) VALUES(?, ?)", (slot, self._store._clock()))
            db.execute("UPDATE model_slots SET effort=?, updated_at=? WHERE slot=?", (effort, self._store._clock(), slot))
        return self.listing()["slots"][slot]

    def resolve(self, slot: str) -> list[dict[str, Any]]:
        """The models to try for a job, in order: main, then backup."""
        with self._store._lock:
            row = self._store._db.execute("SELECT * FROM model_slots WHERE slot=?", (slot,)).fetchone()
        chain = []
        for role in ROLES:
            if row is None or not row[f"{role}_source"]:
                continue
            try:
                source = self._row(row[f"{role}_source"])
            except ApiError:
                continue
            chain.append(
                {
                    "role": role,
                    "source_id": source["id"],
                    "name": source["name"],
                    "base_url": source["base_url"],
                    "protocol": source["protocol"],
                    "api_key": self.key(source["id"]),
                    "model": row[f"{role}_model"],
                    "builtin": bool(source["builtin"]),
                    "effort": row["effort"] if "effort" in row.keys() else "",
                }
            )
        return chain
