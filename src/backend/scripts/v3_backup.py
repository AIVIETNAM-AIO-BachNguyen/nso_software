"""Portable logical backup/restore for an offline or quiesced deployment.

Backups contain sensitive records. Files are created mode 0600, never overwritten.
Restores require an empty target and validate the checksum before any write.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nso.manufacturing.store import SqlDesignStore, store_from_url

TABLES = {
    "designs": ["design_id", "payload", "created_at", "updated_at"],
    "domain_records": ["domain", "record_id", "payload", "created_at"],
    "related_records": ["record_id", "domain", "object_id", "payload", "created_at"],
    "audit_events": ["event_id", "object_id", "payload", "created_at"],
    "counters": ["name", "value"],
    "v3_operations": ["operation_id", "fingerprint", "status_code", "response"],
    "v3_job_leases": ["job_id", "owner", "expires_at"],
}


def snapshot(store):
    if not isinstance(store, SqlDesignStore):
        raise ValueError("A durable SQL store is required")
    with store.transaction():
        with store._connect() as conn:
            data = {
                name: [
                    list(row)
                    for row in conn.cursor()
                    .execute("SELECT " + ",".join(columns) + " FROM " + name)
                    .fetchall()
                ]
                for name, columns in TABLES.items()
            }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return {
        "format": "nso-logical-backup-v1",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "tables": data,
    }


def restore(store, document):
    if not isinstance(store, SqlDesignStore):
        raise ValueError("A durable SQL store is required")
    if document.get("format") != "nso-logical-backup-v1" or set(
        document.get("tables", {})
    ) != set(TABLES):
        raise ValueError("Unsupported backup format")
    data = document["tables"]
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != document["sha256"]:
        raise ValueError("Backup checksum mismatch")
    for name, rows in data.items():
        if any(len(row) != len(TABLES[name]) for row in rows):
            raise ValueError("Invalid backup row")
    with store.transaction():
        with store._connect() as conn:
            for table in TABLES:
                if (
                    table != "counters"
                    and conn.cursor()
                    .execute("SELECT COUNT(*) FROM " + table)
                    .fetchone()[0]
                ):
                    raise ValueError("Restore requires an empty target")
            conn.cursor().execute("DELETE FROM counters")
            for table, rows in data.items():
                statement = store._sql(
                    "INSERT INTO "
                    + table
                    + " ("
                    + ",".join(TABLES[table])
                    + ") VALUES ("
                    + ",".join("?" for _ in TABLES[table])
                    + ")"
                )
                for row in rows:
                    conn.cursor().execute(statement, row)
    return {table: len(rows) for table, rows in data.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    url = os.getenv("NSO_DATABASE_URL", "")
    store = store_from_url(url)
    if args.operation == "backup":
        document = snapshot(store)
        descriptor = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(document, handle)
        print(
            json.dumps(
                {
                    "sha256": document["sha256"],
                    "records": {k: len(v) for k, v in document["tables"].items()},
                }
            )
        )
    else:
        print(json.dumps(restore(store, json.loads(args.file.read_text()))))


if __name__ == "__main__":
    main()
