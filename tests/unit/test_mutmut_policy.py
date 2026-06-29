import ast
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Security-critical modules whose mutation coverage must never silently lapse.
# A surviving mutant in any of these is a real safety regression:
#   - sql_guard: the NL->SQL denylist (forbidden node types + forbidden scan
#     functions); the H-6 projection-position bypass lived here, so a surviving
#     mutant in its checks is a guard bypass.
#   - auth manager / key rotation: API-key issue / verify / rotation.
#   - masking: PII redaction.
#   - rate_limiter: API hot-path / abuse protection.
#   - nl_queries: the only validate_nl_sql() enforcement boundary, plus the
#     pagination SQL wrappers built around prevalidated NL SQL.
#   - sql_builder: every entity/metric SQL string the engine executes is
#     assembled here.
# NOTE: these are the *declared* targets (intent). Actual mutation execution is
# gated by scripts/mutation_report.py (MODULE_TARGETS), which now runs retry.py,
# sql_guard.py AND masking.py live (the serving modules via duckdb-free narrow
# tests, mutated as a top-level `serving` package so mutmut's trampoline accepts
# them). The other serving modules below stay declared-only until they get
# duckdb-free unit tests of their own. These assertions guard the declared
# policy, not live coverage.
REQUIRED_MUTATION_TARGETS = {
    "src/serving/semantic_layer/sql_guard.py",
    "src/serving/api/auth/manager.py",
    "src/serving/api/auth/key_rotation.py",
    "src/serving/masking.py",
    "src/serving/api/rate_limiter.py",
    "src/serving/semantic_layer/query/nl_queries.py",
    "src/serving/semantic_layer/query/sql_builder.py",
}


def _mutmut_paths() -> list[str]:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["mutmut"]["paths_to_mutate"]


def test_mutmut_paths_all_exist() -> None:
    # A path that rots to a missing file makes mutmut silently mutate nothing
    # for that surface — the H-2 bug, where paths_to_mutate pointed at the
    # deleted src/serving/api/auth.py and the auth mutation gate became a no-op.
    # Fail loud if any configured target no longer exists on disk.
    missing = [p for p in _mutmut_paths() if not (PROJECT_ROOT / p).is_file()]
    assert missing == []


def test_mutmut_covers_security_critical_modules() -> None:
    # Keep the security-critical surfaces in the mutation target set so a future
    # refactor cannot quietly drop them (mirrors the per-module coverage pins in
    # test_coverage_policy.py).
    paths = set(_mutmut_paths())
    assert REQUIRED_MUTATION_TARGETS <= paths


def test_mutmut_targets_define_real_logic() -> None:
    # The semantic flavor of the H-2 path-rot bug: after the query-engine
    # package split, paths_to_mutate kept pointing at
    # src/serving/semantic_layer/query_engine.py — a 5-line re-export shim —
    # so mutmut "covered" the query surface while mutating nothing real.
    # The existence check above cannot catch this (the shim is a real file),
    # so also require every target to define at least one function or class
    # at module level; a pure re-export module has only imports/assignments.
    shims = []
    for path in _mutmut_paths():
        tree = ast.parse((PROJECT_ROOT / path).read_text(encoding="utf-8"))
        defines_logic = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in tree.body
        )
        if not defines_logic:
            shims.append(path)
    assert shims == []
