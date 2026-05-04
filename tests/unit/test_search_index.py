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
