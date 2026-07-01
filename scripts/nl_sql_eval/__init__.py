"""NL->SQL evaluation harness for AgentFlow's semantic layer.

Measures the *execution accuracy* (EA) of AgentFlow's NL->SQL translator
(`src.serving.semantic_layer.nl_engine.translate_nl_to_sql`) against a small
labelled gold set over the demo warehouse schema. Ported from the D:\\NL_SQL
LangGraph engine's eval harness (see ADR 0008) so AgentFlow has a real,
reproducible accuracy number instead of an unbacked "NL->SQL works" claim.

The harness is engine-agnostic: it calls whatever `translate_nl_to_sql` is
configured to do (rule-based by default; the GraceKelly/Sonnet-5 LLM path when
`GRACEKELLY_URL` is set), so the same runner measures the current engine today
and the adopted NL_SQL engine after the port (ADR 0008 step 4).
"""

from scripts.nl_sql_eval.dataset import GOLD_SET, GoldItem
from scripts.nl_sql_eval.metrics import (
    ResultComparison,
    compare_results,
    execution_accuracy,
)
from scripts.nl_sql_eval.runner import EvalReport, ItemResult, run_eval
from scripts.nl_sql_eval.warehouse import build_demo_warehouse

__all__ = [
    "GOLD_SET",
    "EvalReport",
    "GoldItem",
    "ItemResult",
    "ResultComparison",
    "build_demo_warehouse",
    "compare_results",
    "execution_accuracy",
    "run_eval",
]
