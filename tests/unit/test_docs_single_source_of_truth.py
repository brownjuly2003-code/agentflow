"""P2-1 ratchet: authoritative docs must match the shipped runtime.

The 2026-07-11 audit found the repo had lost its single source of truth:
the FastAPI/OpenAPI version froze at 1.0.0 while the package moved to
2.0.0, SECURITY.md supported a release line that no longer exists, and
authoritative pages referenced modules deleted months earlier. `mkdocs
build --strict` never sees most of these files (mkdocs.yml excludes
them), so this suite is the reference checker CI actually runs.

Point-in-time records (ADRs, dated perf/audit reports, the CHANGELOG)
are exempt from the removed-path scan: they describe the repo as it was,
not as it is.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Docs that make claims about the CURRENT state of the system. Dated
# reports and ADRs under docs/ stay historical on purpose.
AUTHORITATIVE_DOCS = (
    "README.md",
    "SECURITY.md",
    "docs/architecture.md",
    "docs/security-audit.md",
    "docs/release-readiness.md",
    "docs/deployment.md",
    "docs/runbook.md",
)

# Modules the runtime deleted; a current-state doc citing one as evidence
# is describing a control that no longer exists (audit P2-1).
REMOVED_PATHS = (
    "src/agentflow_runtime/serving/masking.py",
    "src/agentflow_runtime/serving/pii_policy.py",
    "config/pii_fields.yaml",
    "tests/unit/test_masking.py",
)

# Directories whose *.md files are point-in-time records.
HISTORICAL_DOC_DIRS = (
    "docs/decisions",
    "docs/perf",
    "docs/dv2-multi-branch",
    "docs/migration",
)


def _package_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["version"]


def _current_state_docs() -> list[Path]:
    docs = [ROOT / "README.md", ROOT / "SECURITY.md"]
    for path in sorted((ROOT / "docs").rglob("*.md")):
        relative = path.relative_to(ROOT).as_posix()
        if any(relative.startswith(prefix + "/") for prefix in HISTORICAL_DOC_DIRS):
            continue
        docs.append(path)
    return docs


def test_runtime_version_helper_reports_the_package_version() -> None:
    # The source checkout outranks installed distribution metadata: an
    # editable install records the version at install time and goes stale
    # the moment pyproject.toml is bumped.
    from agentflow_runtime.version import runtime_version

    assert runtime_version() == _package_version()


def test_fastapi_app_reports_the_package_version() -> None:
    from agentflow_runtime.serving.api.main import app

    assert app.version == _package_version()


def test_committed_openapi_artifact_carries_the_package_version() -> None:
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))

    assert spec["info"]["version"] == _package_version()


def test_helm_chart_app_version_matches_the_package() -> None:
    chart = yaml.safe_load((ROOT / "helm" / "agentflow" / "Chart.yaml").read_text(encoding="utf-8"))

    assert str(chart["appVersion"]) == _package_version()


def test_security_policy_supports_the_current_major_line() -> None:
    major = _package_version().split(".")[0]
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    # Exactly one "(current)" row in the supported-versions table, and it
    # names the major line the package actually ships.
    current_lines = re.findall(r"`(\d+)\.x`\s*\(current\)", text)
    assert current_lines == [major]
    assert f"`v{major}.x` line" in text or f"`{major}.x` line" in text


def test_release_readiness_tracks_the_current_release_line() -> None:
    text = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")

    match = re.search(r"\*\*Release line\*\*: `v(\d+\.\d+\.\d+)`", text)
    assert match is not None, "release-readiness.md lost its release-line header"
    assert match.group(1) == _package_version()

    # The doc may not claim a required-check count that contradicts its own
    # enumerated list (the audit caught "12" against a 13-check reality).
    counts = {int(n) for n in re.findall(r"(\d+) required status checks", text)}
    listed = re.search(r"required status checks[^\n]*—([^.]+)\.", text)
    assert listed is not None, "release-readiness.md no longer enumerates the checks"
    check_names = re.findall(r"`([a-z0-9-]+)`", listed.group(1))
    assert counts == {len(check_names)}, (
        f"claimed count(s) {sorted(counts)} != enumerated {len(check_names)} checks"
    )


def test_current_state_docs_do_not_cite_removed_modules() -> None:
    offenders: list[str] = []
    for doc in _current_state_docs():
        text = doc.read_text(encoding="utf-8")
        for removed in REMOVED_PATHS:
            if removed in text:
                offenders.append(f"{doc.relative_to(ROOT).as_posix()} -> {removed}")

    assert offenders == []


def test_current_state_docs_carry_no_replacement_characters() -> None:
    # U+FFFD in a committed doc means an encoding accident already
    # happened; the next save can only make it worse.
    offenders = [
        doc.relative_to(ROOT).as_posix()
        for doc in _current_state_docs()
        if "�" in doc.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_authoritative_docs_relative_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
    offenders: list[str] = []
    for name in AUTHORITATIVE_DOCS:
        doc = ROOT / name
        for target in link_pattern.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = (doc.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                offenders.append(f"{name} -> {target}")

    assert offenders == []


def test_architecture_walkthrough_defers_runtime_claims_to_reference() -> None:
    walkthrough = (ROOT / "docs" / "architecture" / "index.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "[detailed architecture reference](../architecture.md)" in walkthrough
    assert "[engineering status](../STATUS.md)" in walkthrough
    assert "[architecture walkthrough](architecture/index.md)" in reference

    assert 'serving_materializer["Serving materializer"]' in walkthrough
    assert 'lake_materializer["Lake materializer"]' in walkthrough
    assert 'serving_store["Configured serving store"]' in walkthrough
    for backend_claim in ("DuckDB", "ClickHouse", "Iceberg"):
        assert backend_claim not in walkthrough

    assert len(walkthrough.split()) * 2 < len(reference.split())


def test_api_walkthrough_defers_mutable_contract_to_reference() -> None:
    walkthrough = (ROOT / "docs" / "api" / "index.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")

    assert "[full API reference](../api-reference.md)" in walkthrough
    assert "[API walkthrough](api/index.md)" in reference

    for core_step in ("/v1/health", "/v1/catalog", "/v1/entity/", "/v1/query"):
        assert core_step in walkthrough

    for reference_owned_claim in (
        "X-Admin-Key",
        "X-AgentFlow-Version",
        "X-Correlation-ID",
        "/v1/admin/*",
        "/v1/deadletter",
        "/v1/webhooks",
        "up to 20",
    ):
        assert reference_owned_claim in reference
        assert reference_owned_claim not in walkthrough


def test_deployment_walkthrough_defers_helm_contract_to_operator_reference() -> None:
    walkthrough = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs" / "operations" / "helm-deployment.md").read_text(encoding="utf-8")

    assert "[complete Helm operator reference](operations/helm-deployment.md)" in walkthrough
    assert "[deployment walkthrough](../deployment.md)" in reference
    assert "[engineering status](STATUS.md)" in walkthrough
    assert "[engineering status](../STATUS.md)" in reference

    for local_entrypoint in (
        "python scripts/demo_local.py",
        "make demo",
        "make stack-prod-shaped-local",
    ):
        assert local_entrypoint in walkthrough

    for reference_owned_claim in (
        "helm/agentflow/values-production.yaml",
        "networkPolicy.enabled=true",
        "image.digest",
        "secrets.create=false",
        "ingress.tls",
    ):
        assert reference_owned_claim in reference
        assert reference_owned_claim not in walkthrough

    assert len(walkthrough.split()) * 2 < len(reference.split())


def test_concepts_walkthrough_defers_domain_runtime_and_route_claims() -> None:
    walkthrough = (ROOT / "docs" / "concepts.md").read_text(encoding="utf-8")
    domain = (ROOT / "docs" / "domain.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")

    assert "[detailed domain model](domain.md)" in walkthrough
    assert "[detailed architecture reference](architecture.md)" in walkthrough
    assert "[full API reference](api-reference.md)" in walkthrough
    assert "[engineering status](STATUS.md)" in walkthrough
    assert "[concepts walkthrough](concepts.md)" in domain

    for stable_concept in (
        "## Streaming-first",
        "## Semantic layer",
        "## Contracts",
        "## Query safety",
    ):
        assert stable_concept in walkthrough

    for domain_claim in (
        "`order`",
        "`user`",
        "`product`",
        "`session`",
        "`revenue`",
        "`error_rate`",
    ):
        assert domain_claim in domain
        assert domain_claim not in walkthrough

    for runtime_claim in ("DuckDB", "Iceberg", "Kafka", "Flink", "Redis", "Jaeger", "Grafana"):
        assert runtime_claim in architecture
        assert runtime_claim not in walkthrough

    assert "/v1/contracts" in api_reference
    assert "/v1/contracts" not in walkthrough

    assert len(walkthrough.split()) * 7 < len(domain.split())


def test_observability_walkthrough_defers_operational_contracts_to_owners() -> None:
    walkthrough = (ROOT / "docs" / "observability.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")

    assert "[operational runbook](runbook.md)" in walkthrough
    assert "[full API reference](api-reference.md)" in walkthrough
    assert "[engineering status](STATUS.md)" in walkthrough
    assert "[observability walkthrough](observability.md)" in runbook

    for stable_signal in (
        "## Observability flow",
        "## Metrics",
        "## Traces",
        "## Logs",
    ):
        assert stable_signal in walkthrough

    for runbook_owned_claim in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SDK_DISABLED",
        "scripts/prune_query_analytics.py",
        "30 days",
    ):
        assert runbook_owned_claim in runbook
        assert runbook_owned_claim not in walkthrough

    for api_owned_route in ("/v1/deadletter", "/v1/alerts", "/v1/webhooks"):
        assert api_owned_route in api_reference
        assert api_owned_route not in walkthrough

    assert len(walkthrough.split()) * 3 < len(runbook.split())


def test_components_walkthrough_defers_runtime_inventory_to_architecture_reference() -> None:
    walkthrough = (ROOT / "docs" / "components.md").read_text(encoding="utf-8")
    reference = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "[detailed architecture reference](architecture.md)" in walkthrough
    assert "[engineering status](STATUS.md)" in walkthrough
    assert "[components walkthrough](components.md)" in reference

    for generic_role in (
        'clients["SDKs and direct clients"]',
        'api["Agent API"]',
        'processor["Stream processor"]',
        'lake_store["Configured lake store"]',
        'serving_store["Configured serving store"]',
        'telemetry["Metrics, traces, and logs"]',
    ):
        assert generic_role in walkthrough

    for reference_owned_claim in (
        "FastAPI",
        "DuckDB",
        "Kafka",
        "Flink",
        "Iceberg",
        "Kubernetes",
        "Terraform",
    ):
        assert reference_owned_claim in reference
        assert reference_owned_claim not in walkthrough

    assert len(walkthrough.split()) * 6 < len(reference.split())


def test_curated_landing_defers_runtime_and_status_claims_to_owners() -> None:
    landing = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    project_overview = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")

    assert (
        "[project overview](https://github.com/brownjuly2003-code/agentflow/blob/main/README.md)"
        in landing
    )
    assert "[detailed architecture reference](architecture.md)" in landing
    assert "[engineering status](STATUS.md)" in landing
    assert (
        "[documentation hub](https://github.com/brownjuly2003-code/agentflow/blob/main/docs/README.md)"
        in landing
    )
    assert "[interactive walkthrough](docs/index.md)" in project_overview

    for destination in (
        "quickstart.md",
        "architecture/index.md",
        "concepts.md",
        "components.md",
        "api/index.md",
        "sdk.md",
        "deployment.md",
        "observability.md",
        "troubleshooting.md",
    ):
        assert f"]({destination})" in landing

    for reference_owned_claim in (
        "FastAPI",
        "Kafka",
        "Debezium",
        "PyFlink",
        "DuckDB",
        "Iceberg",
        "ClickHouse",
        "Prometheus",
        "OpenTelemetry",
        "Grafana",
    ):
        assert reference_owned_claim in architecture
        assert reference_owned_claim not in landing

    for status_owned_claim in (
        "production candidate",
        "digest-only staging promotion",
        "BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE",
    ):
        assert status_owned_claim in status
        assert status_owned_claim not in landing

    assert len(landing.split()) * 5 < len(project_overview.split())


def test_troubleshooting_walkthrough_defers_exact_procedures_to_owners() -> None:
    walkthrough = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    contributor_guide = (ROOT / "docs" / "contributing.md").read_text(encoding="utf-8")

    assert "[operational runbook](runbook.md)" in walkthrough
    assert "[troubleshooting walkthrough](troubleshooting.md)" in runbook
    assert "[quickstart](quickstart.md)" in walkthrough
    assert "[deployment walkthrough](deployment.md)" in walkthrough
    assert "[full API reference](api-reference.md)" in walkthrough
    assert "[contributor guide](contributing.md)" in walkthrough

    for stable_section in (
        "## Triage by symptom",
        "## Narrow the boundary",
        "## Choose the verification owner",
    ):
        assert stable_section in walkthrough

    for incident_procedure in (
        "### API does not respond",
        "### Pipeline lag > 60s",
        "### Flink job failed",
        "### Dead letter topic filling up",
        "### Webhook deliveries failing",
    ):
        assert incident_procedure in runbook

    for runbook_owned_command in (
        "docker version",
        "docker compose version",
        "docker compose ps",
        "docker compose logs kafka flink-jobmanager",
        "docker compose down -v",
        "DUCKDB_PATH",
        "--port 8001",
    ):
        assert runbook_owned_command in runbook
        assert runbook_owned_command not in walkthrough

    assert "mkdocs serve -a" in contributor_guide
    assert "mkdocs serve -a" not in walkthrough
    assert "make lint" in contributor_guide
    assert "python -m pytest" in contributor_guide
    assert "python -m ruff" not in walkthrough
    assert "python -m pytest" not in walkthrough

    assert "X-Admin-Key" in api_reference
    assert "X-Admin-Key" not in walkthrough
    assert len(walkthrough.split()) * 5 < len(runbook.split())


def test_sdk_walkthrough_defers_exact_language_and_capability_contracts() -> None:
    walkthrough = (ROOT / "docs" / "sdk.md").read_text(encoding="utf-8")
    python_reference = (ROOT / "sdk" / "README.md").read_text(encoding="utf-8")
    typescript_reference = (ROOT / "sdk-ts" / "README.md").read_text(encoding="utf-8")
    capability_contract = (ROOT / "docs" / "sdk-capabilities.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")

    assert "[quickstart](quickstart.md)" in walkthrough
    assert (
        "[Python package reference](https://github.com/brownjuly2003-code/agentflow/"
        "blob/main/sdk/README.md)" in walkthrough
    )
    assert (
        "[TypeScript package reference](https://github.com/brownjuly2003-code/"
        "agentflow/blob/main/sdk-ts/README.md)" in walkthrough
    )
    assert "[generated capability contract](sdk-capabilities.md)" in walkthrough
    assert "[full API reference](api-reference.md)" in walkthrough
    assert "[SDK walkthrough](../docs/sdk.md)" in python_reference
    assert "[SDK walkthrough](../docs/sdk.md)" in typescript_reference

    for stable_step in (
        "## Choose a client",
        "## Try the same read flow",
        "pip install agentflow-client",
        "npm install @yuliaedomskikh/agentflow-client",
        "client.get_order",
        "client.getOrder",
    ):
        assert stable_step in walkthrough

    language_references = python_reference + typescript_reference
    for language_owned_contract in (
        "AsyncAgentFlowClient",
        "RetryPolicy",
        "configure_resilience",
        "configureResilience",
    ):
        assert language_owned_contract in language_references
        assert language_owned_contract not in walkthrough

    for capability_method in (
        "list_contracts",
        "validate_contract",
        "explain_query",
        "getLineage",
        "getChangelog",
        "isFresh",
    ):
        assert capability_method in capability_contract
        assert capability_method not in walkthrough

    for http_only_route in (
        "/v1/admin/",
        "/v1/webhooks",
        "/v1/alerts",
        "/v1/deadletter",
        "/v1/slo",
        "/v1/stream/events",
    ):
        assert http_only_route in api_reference
        assert http_only_route not in walkthrough

    reference_words = sum(
        len(reference.split())
        for reference in (python_reference, typescript_reference, capability_contract)
    )
    assert len(walkthrough.split()) * 2 < reference_words


def test_quickstart_keeps_first_run_and_defers_adjacent_procedures_to_owners() -> None:
    quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    api_walkthrough = (ROOT / "docs" / "api" / "index.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    contributor_guide = (ROOT / "docs" / "contributing.md").read_text(encoding="utf-8")

    assert "[deployment walkthrough](deployment.md)" in quickstart
    assert "[API walkthrough](api/index.md)" in quickstart
    assert "[full API reference](api-reference.md)" in quickstart
    assert "[contributor guide](contributing.md)" in quickstart
    assert "[quickstart](quickstart.md)" in deployment
    assert "[quickstart](quickstart.md)" in contributor_guide
    assert "[quickstart](../quickstart.md)" in api_walkthrough
    assert "Local demo: `make demo`" not in contributor_guide
    assert "AGENTFLOW_AUTH_DISABLED=true" in deployment
    assert "AGENTFLOW_AUTH_DISABLED=true" not in quickstart
    assert "quickstart's `demo-key`" not in api_walkthrough
    assert "local-only quickstart accepts them without a" in api_walkthrough

    for first_run_step in (
        "## Prerequisites",
        "## Clone and set up",
        "## Start the demo API with No Docker",
        "python scripts/demo_local.py",
        "curl http://localhost:8000/v1/health",
        ". .\\scripts\\setup.ps1",
        "source ./scripts/setup.sh",
    ):
        assert first_run_step in quickstart

    for deployment_owned_command in (
        "python scripts/demo_local.py --prepare-only",
        "make demo",
    ):
        assert deployment_owned_command in deployment
        assert deployment_owned_command not in quickstart

    for contributor_owned_command in (
        'python -m pip install "mkdocs-material>=9.5,<10"',
        "mkdocs serve",
        "mkdocs serve -a 127.0.0.1:8010",
        "mkdocs build --strict",
    ):
        assert contributor_owned_command in contributor_guide
        assert contributor_owned_command not in quickstart

    api_owners = api_walkthrough + api_reference
    for api_owned_contract in (
        '"duckdb_pool"',
        "X-API-Key",
        "/v1/entity/order/ORD-20260404-1001",
        "top products by revenue today",
    ):
        assert api_owned_contract in api_owners
        assert api_owned_contract not in quickstart

    owner_words = sum(
        len(owner.split()) for owner in (deployment, api_walkthrough, contributor_guide)
    )
    assert len(quickstart.split()) * 5 < owner_words
