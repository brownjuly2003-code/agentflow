from collections import Counter

from src.serving.semantic_layer.search_index import SearchDocument, SearchIndex


def test_search_matches_status_plural_edge_case() -> None:
    index = SearchIndex(catalog=None, query_engine=None)  # type: ignore[arg-type]
    tokens = Counter(index._tokenize("Order status shipped"))
    index._documents = [
        SearchDocument(
            doc_type="entity",
            doc_id="order-1",
            entity_type="order",
            endpoint="/v1/entity/order/order-1",
            snippet="Order order-1 status shipped",
            tokens=tokens,
        )
    ]
    index._document_frequency = dict.fromkeys(tokens, 1)

    results = index.search("statuses")

    assert [result["id"] for result in results] == ["order-1"]


def _authorization_index() -> SearchIndex:
    """Four documents that all match "electronics". The three forbidden ones
    score above the single allowed order, so a post-filter applied to the
    response could only ever return fewer rows than the caller asked for."""
    index = SearchIndex(catalog=None, query_engine=None)  # type: ignore[arg-type]
    index._documents = [
        SearchDocument(
            doc_type="entity",
            doc_id="user-1",
            entity_type="user",
            endpoint="/v1/entity/user/user-1",
            snippet="User user-1 prefers electronics",
            tokens=Counter({"electronic": 8}),
        ),
        SearchDocument(
            doc_type="entity",
            doc_id="product-1",
            entity_type="product",
            endpoint="/v1/entity/product/product-1",
            snippet="Product product-1 category electronics",
            tokens=Counter({"electronic": 6}),
        ),
        SearchDocument(
            doc_type="catalog_field",
            doc_id="user.preferred_category",
            entity_type="user",
            endpoint="/v1/catalog",
            snippet="user.preferred_category: electronics, home",
            tokens=Counter({"electronic": 4}),
        ),
        SearchDocument(
            doc_type="entity",
            doc_id="order-1",
            entity_type="order",
            endpoint="/v1/entity/order/order-1",
            snippet="Order order-1 of electronics",
            tokens=Counter({"electronic": 1}),
        ),
        SearchDocument(
            doc_type="metric",
            doc_id="electronics_revenue",
            entity_type=None,
            endpoint="/v1/metrics/electronics_revenue",
            snippet="Metric electronics_revenue",
            tokens=Counter({"electronic": 2}),
        ),
    ]
    index._document_frequency = {"electronic": 5}
    return index


def test_authorized_entity_types_drops_forbidden_documents_before_scoring() -> None:
    index = _authorization_index()

    results = index.search("electronics", authorized_entity_types=["order"])

    assert {result["entity_type"] for result in results} == {"order", None}
    assert "user-1" not in {result["id"] for result in results}


def test_forbidden_documents_do_not_consume_limit_slots() -> None:
    # Regression: the allowlist used to be applied to the response, after
    # [:limit]. The two highest-scoring rows here are forbidden, so an allowed
    # key asking for two results got an empty list back (audit P0-4).
    index = _authorization_index()

    results = index.search("electronics", limit=2, authorized_entity_types=["order"])

    assert "order-1" in {result["id"] for result in results}


def test_metric_documents_survive_a_scoped_allowlist() -> None:
    # /v1/metrics/* is not entity-scoped, so an entity allowlist must not hide
    # metric documents from a scoped key.
    index = _authorization_index()

    results = index.search("electronics", authorized_entity_types=["order"])

    assert "electronics_revenue" in {result["id"] for result in results}


def test_empty_allowlist_drops_every_entity_scoped_document() -> None:
    index = _authorization_index()

    results = index.search("electronics", authorized_entity_types=[])

    assert results
    assert all(result["entity_type"] is None for result in results)


def test_catalog_field_documents_follow_the_entity_allowlist() -> None:
    # A catalog_field document describes one entity type; a key that cannot read
    # that entity should not get its field descriptions through search either.
    index = _authorization_index()

    results = index.search("electronics", authorized_entity_types=["order"])

    assert "user.preferred_category" not in {result["id"] for result in results}


def test_unrestricted_key_still_sees_every_document() -> None:
    index = _authorization_index()

    results = index.search("electronics", limit=10)

    assert len(results) == 5
