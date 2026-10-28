"""Atomic idempotency reservations, shared by API processes using one SQL store."""

import json
import threading

from .manufacturing.store import SqlDesignStore
from .research import ResearchError

_memory_lock = threading.Lock()


class Operations:
    def __init__(self, store):
        self.store = store

    def reserve(self, key, fingerprint):
        if isinstance(self.store, SqlDesignStore):
            with self.store._connect() as conn:
                row = (
                    conn.cursor()
                    .execute(
                        self.store._sql(
                            "INSERT INTO v3_operations (operation_id, fingerprint) VALUES (?, ?) "
                            "ON CONFLICT (operation_id) DO NOTHING RETURNING operation_id"
                        ),
                        (key, fingerprint),
                    )
                    .fetchone()
                )
                conn.commit()
                if row:
                    return None
                stored = (
                    conn.cursor()
                    .execute(
                        self.store._sql(
                            "SELECT fingerprint, status_code, response FROM v3_operations WHERE operation_id = ?"
                        ),
                        (key,),
                    )
                    .fetchone()
                )
        else:
            with _memory_lock:
                if not hasattr(self.store, "_v3_operations"):
                    self.store._v3_operations = {}
                if key not in self.store._v3_operations:
                    self.store._v3_operations[key] = (fingerprint, None, None)
                    return None
                stored = self.store._v3_operations[key]
        if stored[0] != fingerprint:
            raise ResearchError(
                "IDEMPOTENCY_CONFLICT", "This key was used with different input.", 409
            )
        if stored[1] is None:
            raise ResearchError(
                "OPERATION_PENDING",
                "Operation reserved; inspect its audit trail before recovery.",
                409,
            )
        return stored[1], json.loads(stored[2])

    def finish(self, key, fingerprint, status, response):
        encoded = json.dumps(response, allow_nan=False)
        if isinstance(self.store, SqlDesignStore):
            with self.store._connect() as conn:
                conn.cursor().execute(
                    self.store._sql(
                        "UPDATE v3_operations SET status_code = ?, response = ? WHERE operation_id = ? AND fingerprint = ?"
                    ),
                    (status, encoded, key, fingerprint),
                )
                conn.commit()
        else:
            with _memory_lock:
                self.store._v3_operations[key] = (fingerprint, status, encoded)
