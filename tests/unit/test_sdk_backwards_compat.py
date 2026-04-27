import inspect
import re
import tomllib
import warnings
from pathlib import Path

from agentflow import AgentFlowClient, AsyncAgentFlowClient, __version__
from agentflow._compat import deprecated
from agentflow.exceptions import (
    AgentFlowError,
    AuthError,
    DataFreshnessError,
    EntityNotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from agentflow.models import OrderEntity

SDK_ROOT = Path(__file__).resolve().parents[2] / "sdk"


def test_version_is_exposed_from_package():
    assert __version__ == "1.1.0"
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:rc\d+)?", __version__)


def test_package_exports_core_public_api():
    import agentflow

    assert agentflow.__all__ == [
        "AgentFlowClient",
        "AsyncAgentFlowClient",
        "PermissionDeniedError",
        "CircuitOpenError",
        "__version__",
    ]


def test_client_constructor_signature():
    sig = inspect.signature(AgentFlowClient.__init__)

    assert tuple(sig.parameters) == (
        "self",
        "base_url",
        "api_key",
        "timeout",
        "contract_version",
        "api_version",
    )
    assert sig.parameters["timeout"].default == 10.0
    assert sig.parameters["contract_version"].default is None
    assert sig.parameters["api_version"].default is None


def test_async_client_constructor_signature():
    sig = inspect.signature(AsyncAgentFlowClient.__init__)

    assert tuple(sig.parameters) == (
        "self",
        "base_url",
        "api_key",
        "timeout",
        "contract_version",
        "api_version",
    )
    assert sig.parameters["timeout"].default == 10.0
    assert sig.parameters["contract_version"].default is None
    assert sig.parameters["api_version"].default is None


def test_client_public_methods_exist():
    public_methods = {
        "get_order",
        "get_entity",
        "get_user",
        "get_product",
        "get_session",
        "get_metric",
        "explain_query",
        "search",
        "list_contracts",
        "get_contract",
        "diff_contracts",
        "validate_contract",
        "get_lineage",
        "get_changelog",
        "query",
        "health",
        "is_fresh",
        "catalog",
        "batch",
        "batch_entity",
        "batch_metric",
        "batch_query",
    }

    assert public_methods.issubset(set(dir(AgentFlowClient)))


def test_async_client_public_methods_exist():
    public_methods = {
        "get_order",
        "get_entity",
        "get_user",
        "get_product",
        "get_session",
        "get_metric",
        "explain_query",
        "search",
        "list_contracts",
        "get_contract",
        "diff_contracts",
        "validate_contract",
        "get_lineage",
        "get_changelog",
        "query",
        "health",
        "is_fresh",
        "catalog",
        "batch",
        "batch_entity",
        "batch_metric",
        "batch_query",
        "__aenter__",
        "__aexit__",
    }

    assert public_methods.issubset(set(dir(AsyncAgentFlowClient)))


def test_order_entity_required_fields():
    required = {
        "order_id",
        "status",
        "total_amount",
        "user_id",
        "created_at",
    }

    actual = set(OrderEntity.model_fields)
    assert required.issubset(actual), f"Breaking: removed {required - actual}"


def test_exceptions_importable():
    assert AgentFlowError
    assert AuthError
    assert RateLimitError
    assert DataFreshnessError
    assert EntityNotFoundError
    assert PermissionDeniedError


def test_deprecated_decorator_emits_warning_with_replacement_and_removal_version():
    @deprecated(replacement="new_method", removed_in="2.0.0")
    def old_method(value: int) -> int:
        return value + 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = old_method(41)

    assert result == 42
    assert len(caught) == 1
    warning = caught[0]
    assert warning.category is DeprecationWarning
    assert "old_method" in str(warning.message)
    assert "new_method" in str(warning.message)
    assert "2.0.0" in str(warning.message)


def test_deprecated_decorator_preserves_wrapped_metadata():
    @deprecated(replacement="new_method", removed_in="2.0.0")
    def old_method() -> str:
        return "ok"

    assert old_method.__name__ == "old_method"


def test_sdk_pyproject_version_matches_release():
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == "1.1.0"


def test_changelog_documents_semver_and_deprecation_policy():
    changelog = (SDK_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "MAJOR" in changelog
    assert "MINOR" in changelog
    assert "PATCH" in changelog
    assert "Deprecation policy" in changelog
    assert "## [1.0.0]" in changelog
    assert "## [0.1.0]" in changelog
