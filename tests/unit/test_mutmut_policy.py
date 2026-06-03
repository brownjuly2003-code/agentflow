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
REQUIRED_MUTATION_TARGETS = {
    "src/serving/semantic_layer/sql_guard.py",
    "src/serving/api/auth/manager.py",
    "src/serving/api/auth/key_rotation.py",
    "src/serving/masking.py",
    "src/serving/api/rate_limiter.py",
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
