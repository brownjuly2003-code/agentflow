"""Process-wide serialization for DuckDB catalog DDL.

DuckDB raises a ``Catalog write-write conflict`` when two threads run catalog
DDL (CREATE/ALTER) concurrently — even on *different* tables — because the
catalog is a single versioned structure. The serving API offloads its read
handlers onto worker threads (``run_in_threadpool``), and each lazily ensures
its backing table (``CREATE TABLE IF NOT EXISTS`` / ``ALTER ... ADD COLUMN IF
NOT EXISTS``) on a fresh cursor; on a cold DB (the default serving store is
``:memory:``, cold on every restart) a concurrent burst raced and surfaced
HTTP 500s. Serialize every such lazy table-creation behind this one lock so the
first thread creates and the rest see a warm no-op. (audit_30 A2 follow-up:
the #120 read-handler offload race)
"""

from __future__ import annotations

import threading

# A single process-wide lock guarding all lazy DuckDB catalog DDL. Held only for
# the brief CREATE/ALTER IF NOT EXISTS (a near-instant no-op once warm), never
# around query execution and never nested, so it cannot deadlock. A cross-table
# conflict (not just same-table) is real in DuckDB, so the lock is shared across
# every ensure_*_table helper rather than one lock per table.
catalog_ddl_lock = threading.Lock()
