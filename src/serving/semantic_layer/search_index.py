import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import duckdb
import structlog

from src.serving.semantic_layer.catalog import DataCatalog, EntityDefinition, MetricDefinition
from src.serving.semantic_layer.query_engine import QueryEngine

logger = structlog.get_logger()

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


class SearchIndex:
    def __init__(self, catalog: DataCatalog, query_engine: QueryEngine) -> None:
        self.catalog = catalog
        self.query_engine = query_engine
        self._documents: list[SearchDocument] = []
        self._document_frequency: dict[str, int] = {}
        self._rebuilt_at: datetime | None = None

    def rebuild(self) -> None:
        documents: list[SearchDocument] = []

        for entity in self.catalog.entities.values():
            documents.extend(self._entity_documents(entity))
            documents.extend(self._catalog_field_documents(entity))

        for metric in self.catalog.metrics.values():
            documents.append(self._metric_document(metric))

        document_frequency: Counter[str] = Counter()
        for document in documents:
            document_frequency.update(document.tokens.keys())

        self._documents = documents
        self._document_frequency = dict(document_frequency)
        self._rebuilt_at = datetime.now()
        logger.info("search_index_rebuilt", documents=len(documents))

    async def rebuild_periodically(self, interval_seconds: int = 60) -> None:
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                self.rebuild()
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
    ) -> list[dict]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        allowed_entity_types = set(entity_types or [])
        query_counts = Counter(query_tokens)
        scored_documents: list[tuple[float, SearchDocument]] = []
        max_score = 0.0

        for document in self._documents:
            if allowed_entity_types:
                if document.doc_type == "metric":
                    continue
                if document.entity_type not in allowed_entity_types:
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

        results = []
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

    def _entity_documents(self, entity: EntityDefinition) -> list[SearchDocument]:
        try:
            rows = self.query_engine._conn.execute(
                f"SELECT * FROM {entity.table}"  # nosec B608 - entity.table comes from the catalog definition
            ).fetchall()
            columns = [description[0] for description in self.query_engine._conn.description]
        except duckdb.Error:
            logger.exception("search_index_entity_scan_failed", entity_type=entity.name)
            return []

        documents = []
        for row in rows:
            payload = dict(zip(columns, row, strict=False))
            entity_id = str(payload.get(entity.primary_key, ""))
            if not entity_id:
                continue

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
            documents.append(
                SearchDocument(
                    doc_type="entity",
                    doc_id=entity_id,
                    entity_type=entity.name,
                    endpoint=f"/v1/entity/{entity.name}/{entity_id}",
                    snippet=snippet,
                    tokens=Counter(self._tokenize(search_text)),
                    boost=1.0,
                )
            )
        return documents

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
                f"category {payload.get('category')} price {payload.get('price')} USD "
                f"{stock_status}"
            )
        if entity.name == "user":
            return (
                f"User {payload.get('user_id')} with {payload.get('total_orders')} orders "
                f"spent {payload.get('total_spent')} USD "
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
        if len(token) > 4 and token.endswith("ies"):
            token = f"{token[:-3]}y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        return token
