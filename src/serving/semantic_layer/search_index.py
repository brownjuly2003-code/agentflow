import asyncio
import math
import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict

import structlog
from starlette.concurrency import run_in_threadpool

from src.serving.backends import BackendExecutionError
from src.serving.semantic_layer.catalog import DataCatalog, EntityDefinition, MetricDefinition
from src.serving.semantic_layer.query_engine import QueryEngine

logger = structlog.get_logger()

# The index materializes every row it reads, and holds the old and the new set
# at once during a rebuild. The scan used to be an unbounded `SELECT *`, which
# grows with the serving data — so it is capped, and truncation is logged rather
# than a partial index being served as if it were whole (audit P1-6).
DEFAULT_ENTITY_SCAN_LIMIT = int(os.getenv("AGENTFLOW_SEARCH_SCAN_LIMIT", "10000"))

# Incremental refresh (audit P1-6). Each periodic tick reads the journal past
# the cursor instead of full-scanning every entity table: no new events means
# no work at all, a small change-set means a targeted re-read of exactly those
# rows. A full rebuild still happens when the journal window overflows (the
# tick can no longer prove it saw every change), when the changed-id set is
# large enough that targeted reads stop being cheaper, and unconditionally
# every FULL_REBUILD_TICKS ticks — the safety net for writers that bypass the
# journal (batch loads) and for row deletions the journal never mentions.
DEFAULT_REFRESH_WINDOW_ROWS = int(os.getenv("AGENTFLOW_SEARCH_REFRESH_WINDOW", "1000"))
DEFAULT_CHANGED_IDS_LIMIT = int(os.getenv("AGENTFLOW_SEARCH_CHANGED_IDS_LIMIT", "512"))
DEFAULT_FULL_REBUILD_TICKS = int(os.getenv("AGENTFLOW_SEARCH_FULL_REBUILD_TICKS", "10"))

# Journal columns that can carry an id of a row in SOME entity table. The
# refresh does not map event families to tables: it collects every id-shaped
# value and asks each entity table which of them it owns (a bounded IN scan).
# An order event therefore refreshes both the order row it names and the
# users_enriched aggregate it moved, without a fragile family->table map.
_EVENT_ID_COLUMNS = ("entity_id", "order_id", "user_id", "product_id", "session_id")

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@dataclass
class SearchDocument:
    doc_type: Literal["entity", "metric", "catalog_field"]
    doc_id: str
    entity_type: str | None
    endpoint: str
    snippet: str
    tokens: Counter[str]
    boost: float = 1.0
    # Whose row this document was built from. One index serves every tenant (it
    # is built once per process), so the tenant travels *on the document* and
    # `search` filters by it — without this, a shared ClickHouse table would let
    # one tenant's query return another's ids and snippets (audit P0-1).
    # ``None`` on documents that describe the catalog rather than a row (metric,
    # catalog_field): those are the same for everyone.
    tenant_id: str | None = None


class SearchHit(TypedDict):
    """A serialized search result. A ``TypedDict``, not an object: reading it
    with attribute access silently disabled the router's entity allowlist
    (audit_gpt_11_07_26.md P0-4), so the mapping shape is now part of the
    signature and mypy rejects ``hit.entity_type``."""

    type: Literal["entity", "metric", "catalog_field"]
    id: str
    entity_type: str | None
    score: float
    snippet: str
    endpoint: str


class SearchIndex:
    def __init__(
        self,
        catalog: DataCatalog,
        query_engine: QueryEngine,
        *,
        entity_scan_limit: int = DEFAULT_ENTITY_SCAN_LIMIT,
        refresh_window_rows: int = DEFAULT_REFRESH_WINDOW_ROWS,
        changed_ids_limit: int = DEFAULT_CHANGED_IDS_LIMIT,
        full_rebuild_ticks: int = DEFAULT_FULL_REBUILD_TICKS,
    ) -> None:
        self.catalog = catalog
        self.query_engine = query_engine
        self._entity_scan_limit = entity_scan_limit
        self._refresh_window_rows = refresh_window_rows
        self._changed_ids_limit = changed_ids_limit
        self._full_rebuild_ticks = full_rebuild_ticks
        self._documents: dict[tuple[str, str | None, str | None, str], SearchDocument] = {}
        self._document_frequency: Counter[str] = Counter()
        self._rebuilt_at: datetime | None = None
        # Incremental state: the journal watermark the last pass is known to
        # have covered, and how many ticks ago the last FULL pass ran.
        self._journal_cursor: datetime | None = None
        self._ticks_since_full_rebuild = 0

    @staticmethod
    def _document_key(document: SearchDocument) -> tuple[str, str | None, str | None, str]:
        # tenant_id is part of identity: two tenants may legitimately hold
        # rows with the same primary key (audit P0-1), and each gets its own
        # document.
        return (document.doc_type, document.entity_type, document.tenant_id, document.doc_id)

    def rebuild(self) -> None:
        # Probe the journal frontier BEFORE scanning: events that land during
        # the scan fall after the cursor and get re-processed by the next
        # refresh (an idempotent upsert), instead of being skipped forever.
        cursor_candidate = self._journal_frontier()

        documents: dict[tuple[str, str | None, str | None, str], SearchDocument] = {}
        for entity in self.catalog.entities.values():
            for document in self._entity_documents(entity):
                documents[self._document_key(document)] = document
            for document in self._catalog_field_documents(entity):
                documents[self._document_key(document)] = document

        for metric in self.catalog.metrics.values():
            document = self._metric_document(metric)
            documents[self._document_key(document)] = document

        document_frequency: Counter[str] = Counter()
        for document in documents.values():
            document_frequency.update(document.tokens.keys())

        self._documents = documents
        self._document_frequency = document_frequency
        self._rebuilt_at = datetime.now()
        self._journal_cursor = cursor_candidate
        self._ticks_since_full_rebuild = 0
        logger.info("search_index_rebuilt", documents=len(documents))

    def refresh(self) -> str:
        """One periodic maintenance tick (audit P1-6). Returns what it did:

        - ``"noop"`` — the journal shows nothing new past the cursor; the
          tick cost one bounded journal read and zero table scans.
        - ``"incremental"`` — a small change-set was re-read row-by-row
          (``scan_entity_rows_by_ids``) and upserted in place; document
          frequencies are maintained incrementally.
        - ``"full:*"`` — a full rebuild ran, and the suffix says why:
          ``scheduled`` (every ``full_rebuild_ticks`` ticks — the safety net
          for journal-bypassing writers and deletions), ``overflow`` (more
          new events than the journal window, so completeness is unprovable),
          ``changed-set`` (targeted reads would not be cheaper any more), or
          ``cold`` (no cursor yet).
        """
        self._ticks_since_full_rebuild += 1
        if self._journal_cursor is None:
            self.rebuild()
            return "full:cold"
        if self._ticks_since_full_rebuild >= self._full_rebuild_ticks:
            self.rebuild()
            return "full:scheduled"

        events = list(
            self.query_engine.fetch_pipeline_events(
                limit=self._refresh_window_rows,
                newest_first=True,
                min_processed_at=self._journal_cursor,
            )
            or []
        )
        # min_processed_at is inclusive, so the boundary rows come back every
        # tick — advance strictly past the cursor or do nothing.
        fresh: list[dict] = []
        frontier = self._journal_cursor
        for event in events:
            processed_at = self._parse_processed_at(event.get("processed_at"))
            if processed_at is None or processed_at <= self._journal_cursor:
                continue
            fresh.append(event)
            frontier = max(frontier, processed_at)
        if not fresh:
            return "noop"
        if len(events) >= self._refresh_window_rows:
            self.rebuild()
            return "full:overflow"

        changed_ids: set[str] = set()
        for event in fresh:
            for column in _EVENT_ID_COLUMNS:
                value = event.get(column)
                if value:
                    changed_ids.add(str(value))
        if len(changed_ids) > self._changed_ids_limit:
            self.rebuild()
            return "full:changed-set"

        self._apply_changed_ids(changed_ids)
        self._journal_cursor = frontier
        return "incremental"

    async def rebuild_periodically(self, interval_seconds: int = 60) -> None:
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                # A tick full-scanned and re-tokenized every entity table and
                # ran a live metric query per metric, every 60 seconds, per
                # replica (audit P1-6). refresh() reads the journal past the
                # cursor instead and falls back to the full pass only when it
                # must. Still off the event loop: even the incremental path
                # does synchronous backend I/O. (audit_28_06_26.md #16)
                outcome = await run_in_threadpool(self.refresh)
                if outcome != "noop":
                    logger.info("search_index_refreshed", outcome=outcome)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("search_index_rebuild_failed")

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        entity_types: list[str] | None = None,
        authorized_entity_types: Iterable[str] | None = None,
        tenant_id: str | None = None,
    ) -> list[SearchHit]:
        """Score indexed documents against ``query``.

        ``entity_types`` is the caller's optional narrowing filter.

        ``authorized_entity_types`` is the API key's allowlist: ``None`` means
        unrestricted, an empty collection means no entity-scoped document at
        all. It is enforced here, before scoring, so a forbidden document never
        enters the candidate set — filtering it out of the response afterwards
        would still let it consume a ``limit`` slot and crowd out the rows the
        key is allowed to see (audit_gpt_11_07_26.md P0-4).

        ``tenant_id`` is the calling tenant. The index is global — one corpus per
        process, holding every tenant's rows — so this is what keeps a shared
        serving table from answering one tenant with another's ids and snippets
        (audit P0-1). Enforced before scoring, for the same reason as the
        allowlist. ``None`` means an unscoped read, reachable only with auth
        disabled, exactly as on every other read surface.
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        authorized = None if authorized_entity_types is None else set(authorized_entity_types)
        requested_entity_types = set(entity_types or [])
        query_counts = Counter(query_tokens)
        scored_documents: list[tuple[float, SearchDocument]] = []
        max_score = 0.0

        for document in self._documents.values():
            # Documents built from a row belong to the tenant that wrote it.
            # Catalog documents (metric, catalog_field) carry no tenant — they
            # describe the schema, which is the same for everyone.
            if (
                tenant_id is not None
                and document.tenant_id is not None
                and document.tenant_id != tenant_id
            ):
                continue

            # Entity and catalog_field documents describe one entity type and
            # are reachable only by a key allowed that type. Metric documents
            # carry no entity_type: /v1/metrics/* is not entity-scoped, so they
            # stay visible to scoped keys.
            if (
                authorized is not None
                and document.entity_type is not None
                and document.entity_type not in authorized
            ):
                continue

            if requested_entity_types:
                if document.doc_type == "metric":
                    continue
                if document.entity_type not in requested_entity_types:
                    continue

            matched = 0
            score = 0.0
            for token, query_count in query_counts.items():
                term_count = document.tokens.get(token, 0)
                if term_count == 0:
                    continue
                matched += 1
                score += query_count * (1.0 + math.log(term_count)) * self._idf(token)

            if score == 0.0:
                continue

            coverage = matched / len(query_counts)
            score = score * (0.65 + 0.35 * coverage) * document.boost
            scored_documents.append((score, document))
            max_score = max(max_score, score)

        scored_documents.sort(key=lambda item: (-item[0], item[1].doc_type, item[1].doc_id))

        results: list[SearchHit] = []
        for score, document in scored_documents[:limit]:
            normalized_score = round(score / max_score, 4) if max_score else 0.0
            results.append(
                {
                    "type": document.doc_type,
                    "id": document.doc_id,
                    "entity_type": document.entity_type,
                    "score": normalized_score,
                    "snippet": document.snippet,
                    "endpoint": document.endpoint,
                }
            )
        return results

    def _idf(self, token: str) -> float:
        total_documents = len(self._documents)
        frequency = self._document_frequency.get(token, 0)
        return math.log((1 + total_documents) / (1 + frequency)) + 1.0

    # --- incremental maintenance (audit P1-6) ---------------------------------

    def _journal_frontier(self) -> datetime | None:
        """Newest journal timestamp, or None when the journal is empty or
        unreadable (the next refresh then goes ``full:cold`` — fail toward
        rebuilding, never toward silently skipping changes)."""
        try:
            newest = self.query_engine.fetch_pipeline_events(limit=1, newest_first=True)
        except Exception:
            logger.exception("search_index_journal_frontier_failed")
            return None
        if not newest:
            return None
        return self._parse_processed_at(newest[0].get("processed_at"))

    @staticmethod
    def _parse_processed_at(value: object) -> datetime | None:
        # DuckDB hands back datetimes, external backends ISO strings (JSON
        # transport) — same duality fetch_pipeline_events documents.
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _apply_changed_ids(self, changed_ids: set[str]) -> None:
        """Re-read exactly the rows the journal named and upsert their
        documents. No event-family -> table map: every table is asked which
        of the changed ids it owns (bounded IN scans). An id a table returns
        no row for, while the index still holds its document, is a deletion.

        Copy-on-write, like rebuild(): search() runs on the event loop while
        this runs in a worker thread, so the live dict is never mutated — a
        shallow copy takes the batch and swaps in atomically. The copies
        share the (immutable-in-practice) document objects, so the cost is
        the dict itself, not the corpus.
        """
        documents = dict(self._documents)
        frequency = self._document_frequency.copy()
        ids = sorted(changed_ids)
        for entity in self.catalog.entities.values():
            try:
                rows = self.query_engine.scan_entity_rows_by_ids(
                    entity.table,
                    primary_key=entity.primary_key,
                    ids=ids,
                )
            except BackendExecutionError:
                logger.exception("search_index_incremental_scan_failed", entity_type=entity.name)
                continue
            returned: set[tuple[str | None, str]] = set()
            for row in rows:
                document = self._entity_document_from_row(entity, row)
                if document is None:
                    continue
                key = self._document_key(document)
                previous = documents.pop(key, None)
                if previous is not None:
                    frequency.subtract(previous.tokens.keys())
                documents[key] = document
                frequency.update(document.tokens.keys())
                returned.add((document.tenant_id, document.doc_id))
            stale = [
                key
                for key in documents
                if key[0] == "entity"
                and key[1] == entity.name
                and key[3] in changed_ids
                and (key[2], key[3]) not in returned
            ]
            for key in stale:
                previous = documents.pop(key)
                frequency.subtract(previous.tokens.keys())
        # Counter.subtract keeps zero/negative entries alive; compact once per
        # batch so the frequency table shrinks with the corpus.
        self._documents = documents
        self._document_frequency = +frequency

    def _entity_documents(self, entity: EntityDefinition) -> list[SearchDocument]:
        try:
            # Through the active backend. This scan ran on the raw DuckDB
            # connection, so on the ClickHouse profile /v1/search indexed — and
            # answered from — a store nobody was serving (audit P0-3).
            rows = self.query_engine.scan_entity_rows(
                entity.table,
                limit=self._entity_scan_limit,
            )
        except BackendExecutionError:
            logger.exception("search_index_entity_scan_failed", entity_type=entity.name)
            return []

        if len(rows) >= self._entity_scan_limit:
            logger.warning(
                "search_index_entity_scan_truncated",
                entity_type=entity.name,
                limit=self._entity_scan_limit,
            )

        documents = []
        for row in rows:
            document = self._entity_document_from_row(entity, row)
            if document is not None:
                documents.append(document)
        return documents

    def _entity_document_from_row(
        self, entity: EntityDefinition, row: dict
    ) -> SearchDocument | None:
        # The tenant travels on the document, not in it: strip the column
        # before the row is turned into snippet and tokens, so a tenant id
        # never leaks into search text (P0-1).
        tenant_id = str(row.get("tenant_id") or "default")
        payload = {key: value for key, value in row.items() if key != "tenant_id"}
        entity_id = str(payload.get(entity.primary_key, ""))
        if not entity_id:
            return None

        snippet = self._entity_snippet(entity, payload)
        search_text = " ".join(
            part
            for part in (
                entity.name,
                self._pluralize(entity.name),
                entity.description,
                snippet,
                self._payload_text(payload),
                self._entity_tags(entity, payload),
            )
            if part
        )
        return SearchDocument(
            doc_type="entity",
            doc_id=entity_id,
            entity_type=entity.name,
            endpoint=f"/v1/entity/{entity.name}/{entity_id}",
            snippet=snippet,
            tokens=Counter(self._tokenize(search_text)),
            boost=1.0,
            tenant_id=tenant_id,
        )

    def _catalog_field_documents(self, entity: EntityDefinition) -> list[SearchDocument]:
        documents = []
        for field_name, description in entity.fields.items():
            field_id = f"{entity.name}.{field_name}"
            text = " ".join(
                (
                    entity.name,
                    self._pluralize(entity.name),
                    field_name.replace("_", " "),
                    description,
                )
            )
            documents.append(
                SearchDocument(
                    doc_type="catalog_field",
                    doc_id=field_id,
                    entity_type=entity.name,
                    endpoint="/v1/catalog",
                    snippet=f"{field_id}: {description}",
                    tokens=Counter(self._tokenize(text)),
                    boost=0.6,
                )
            )
        return documents

    def _metric_document(self, metric: MetricDefinition) -> SearchDocument:
        default_window = "24h" if "24h" in metric.available_windows else metric.available_windows[0]
        try:
            current_value = self.query_engine.get_metric(metric.name, window=default_window)
            value_text = f"{current_value['value']} {current_value['unit']}"
        except ValueError:
            value_text = f"unavailable {metric.unit}"

        metric_name_text = metric.name.replace("_", " ")
        snippet = (
            f"Metric {metric.name}: {metric.description}. Current value ({default_window}) "
            f"is {value_text}."
        )
        tokens = Counter(
            self._tokenize(
                " ".join(
                    (
                        "metric",
                        metric.name,
                        metric_name_text,
                        metric.description,
                        metric.unit,
                        snippet,
                    )
                )
            )
        )
        return SearchDocument(
            doc_type="metric",
            doc_id=metric.name,
            entity_type=None,
            endpoint=f"/v1/metrics/{metric.name}",
            snippet=snippet,
            tokens=tokens,
            boost=1.15,
        )

    def _entity_snippet(self, entity: EntityDefinition, payload: dict) -> str:
        if entity.name == "order":
            return (
                f"Order {payload.get('order_id')} status {payload.get('status')} "
                f"total {payload.get('total_amount')} {payload.get('currency')} "
                f"user {payload.get('user_id')}"
            )
        if entity.name == "product":
            stock_status = "in stock" if payload.get("in_stock") else "out of stock"
            return (
                f"Product {payload.get('name')} ({payload.get('product_id')}) "
                f"category {payload.get('category')} price {payload.get('price')} RUB "
                f"{stock_status}"
            )
        if entity.name == "user":
            return (
                f"User {payload.get('user_id')} with {payload.get('total_orders')} orders "
                f"spent {payload.get('total_spent')} RUB "
                f"prefers {payload.get('preferred_category')}"
            )
        if entity.name == "session":
            return (
                f"Session {payload.get('session_id')} for user {payload.get('user_id')} "
                f"stage {payload.get('funnel_stage')} conversion {payload.get('is_conversion')}"
            )
        return f"{entity.name} {payload}"

    def _entity_tags(self, entity: EntityDefinition, payload: dict) -> str:
        tags: list[str] = []
        if entity.name == "order":
            total_amount = payload.get("total_amount")
            if total_amount is None:
                amount = 0.0
            else:
                try:
                    amount = float(str(total_amount))
                except ValueError:
                    amount = 0.0

            if amount >= 300:
                tags.extend(["large", "large", "large", "high", "value", "premium"])
            elif amount >= 150:
                tags.extend(["large", "high", "value"])
            elif amount <= 50:
                tags.extend(["small", "budget", "low", "value"])

        if entity.name == "product" and payload.get("in_stock") is False:
            tags.extend(["unavailable", "out", "stock"])

        return " ".join(tags)

    def _payload_text(self, payload: dict) -> str:
        parts: list[str] = []
        for key, value in payload.items():
            parts.append(key.replace("_", " "))
            if value is None:
                continue
            if isinstance(value, datetime):
                parts.append(value.isoformat())
            else:
                parts.append(str(value))
        return " ".join(parts)

    def _pluralize(self, text: str) -> str:
        if text.endswith("s"):
            return text
        if text.endswith("y") and len(text) > 1:
            return f"{text[:-1]}ies"
        return f"{text}s"

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for raw_token in TOKEN_RE.findall(text.lower()):
            token = self._normalize_token(raw_token)
            if not token or token in STOP_WORDS:
                continue
            tokens.append(token)
        return tokens

    def _normalize_token(self, token: str) -> str:
        if token in ("status", "statuses"):
            return "status"
        if len(token) > 4 and token.endswith("ies"):
            token = f"{token[:-3]}y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        return token
