import json

from agentflow import AgentFlowClient
from llama_index.core import Document
from llama_index.core.readers.base import BaseReader


class AgentFlowReader(BaseReader):
    def __init__(self, base_url: str, api_key: str):
        self.client = AgentFlowClient(base_url, api_key)

    def load_data(
        self,
        entity_type: str | None = None,
        metric_names: list[str] | None = None,
        window: str = "24h",
    ) -> list[Document]:
        documents: list[Document] = []

        if entity_type is not None:
            result = self.client.query(f"List {entity_type} entities")
            rows = result.answer if isinstance(result.answer, list) else [result.answer]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                entity_id = row.get(f"{entity_type}_id") or row.get("entity_id") or row.get("id")
                documents.append(
                    Document(
                        text=(
                            f"{entity_type} {entity_id}: "
                            f"{json.dumps(row, sort_keys=True, default=str)}"
                        ),
                        metadata={
                            "entity_type": entity_type,
                            "entity_id": entity_id,
                            "freshness_seconds": row.get("freshness_seconds"),
                            "quality_score": row.get("quality_score"),
                        },
                    )
                )

        for metric_name in metric_names or []:
            metric = self.client.get_metric(metric_name, window)
            documents.append(
                Document(
                    text=(
                        f"metric {metric.metric_name} ({metric.window}): "
                        f"{metric.value} {metric.unit}"
                    ),
                    metadata={
                        "entity_type": "metric",
                        "entity_id": metric.metric_name,
                        "freshness_seconds": None,
                        "quality_score": None,
                        "window": metric.window,
                        "computed_at": metric.computed_at.isoformat(),
                    },
                )
            )

        return documents
