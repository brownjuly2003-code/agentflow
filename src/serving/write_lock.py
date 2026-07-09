"""The one lock that serializes writes on the shared DuckDB write connection.

``DuckDBPool`` hands out a *single* owning write connection and cursors over it
(``src/serving/db_pool.py``), so every in-process writer that issues
``BEGIN``/``COMMIT`` on it must take turns: two concurrent writers would
interleave their transactions on the same connection.

Two writers exist today and both live inside the API process:

* the center node-ingest endpoint (``src/serving/node/ingest.py``), and
* the in-process serving bridge on the DuckDB backend
  (``src/processing/bridge_consumer.py``), which cannot be a separate process
  because the demo store is often ``:memory:`` and is never shareable across
  processes.

They must share *one* lock object — two independent locks would serialize each
writer against itself and against nothing else. Hence this module rather than a
module-private lock in either writer.

Note the scope: this guards the *connection*, not the database file. The
ClickHouse serving backend is out-of-process and multi-writer-safe, so the
standalone bridge never takes this lock.
"""

from __future__ import annotations

import threading

SERVING_WRITE_LOCK = threading.Lock()

__all__ = ["SERVING_WRITE_LOCK"]
