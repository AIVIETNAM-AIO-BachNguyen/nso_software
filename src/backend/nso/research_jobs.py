"""Recoverable, bounded worker leases for training jobs across API processes."""

from contextlib import contextmanager
import time
import uuid

from .manufacturing.store import SqlDesignStore


@contextmanager
def job_lease(store, job_id, seconds=3600):
    owner = uuid.uuid4().hex
    acquired = False
    with store.transaction():
        clock = time.time()
        if isinstance(store, SqlDesignStore):
            with store._connect() as conn:
                row = (
                    conn.cursor()
                    .execute(
                        store._sql(
                            "INSERT INTO v3_job_leases (job_id,owner,expires_at) VALUES (?,?,?) "
                            "ON CONFLICT (job_id) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at "
                            "WHERE v3_job_leases.expires_at <= ? RETURNING owner"
                        ),
                        (job_id, owner, clock + seconds, clock),
                    )
                    .fetchone()
                )
                acquired = bool(row and row[0] == owner)
        else:
            if not hasattr(store, "_v3_leases"):
                store._v3_leases = {}
            prior = store._v3_leases.get(job_id)
            if prior is None or prior[1] <= clock:
                store._v3_leases[job_id] = (owner, clock + seconds)
                acquired = True
    try:
        yield acquired
    finally:
        if acquired:
            with store.transaction():
                if isinstance(store, SqlDesignStore):
                    with store._connect() as conn:
                        conn.cursor().execute(
                            store._sql(
                                "DELETE FROM v3_job_leases WHERE job_id=? AND owner=?"
                            ),
                            (job_id, owner),
                        )
                elif store._v3_leases.get(job_id, (None,))[0] == owner:
                    del store._v3_leases[job_id]
