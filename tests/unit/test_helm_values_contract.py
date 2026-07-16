"""Static Helm values contract checks.

Live Helm CLI schema validation is covered by
tests/integration/test_helm_values_live_validation.py.
"""

import json
import shutil
import subprocess
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = PROJECT_ROOT / "helm" / "agentflow"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_helm_template(*args: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise AssertionError("helm is required for Helm render policy tests")
    return subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH), *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def test_chart_declares_values_schema_for_runtime_contracts():
    schema_path = PROJECT_ROOT / "helm" / "agentflow" / "values.schema.json"

    assert schema_path.exists()

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    api_key_item = schema["properties"]["secrets"]["properties"]["apiKeys"]["properties"]["keys"][
        "items"
    ]
    tenant_item = schema["properties"]["config"]["properties"]["tenants"]["properties"]["tenants"][
        "items"
    ]

    assert "key_id" in api_key_item["required"]
    assert "name" in api_key_item["required"]
    assert "tenant" in api_key_item["required"]
    assert "created_at" in api_key_item["required"]
    assert "id" in tenant_item["required"]
    assert "display_name" in tenant_item["required"]
    assert "create" in schema["properties"]["secrets"]["required"]
    assert "existingSecret" in schema["properties"]["secrets"]["required"]


def test_tenant_schema_does_not_require_the_retired_duckdb_schema_field():
    """`duckdb_schema` is accepted, ignored, and no longer demanded (ADR-004).

    It named the isolation mechanism back when isolation was supposed to be a
    schema per tenant. Nothing creates those schemas and nothing reads the field
    now — the boundary is the `tenant_id` column in each table's write key — so
    requiring operators to declare one would be asking them to name a thing that
    does not exist. The property stays in the schema (tenant items are
    `additionalProperties: false`, so removing it would reject values written for
    the old model) and says so in its description.
    """
    schema = json.loads(
        (PROJECT_ROOT / "helm" / "agentflow" / "values.schema.json").read_text(encoding="utf-8")
    )
    tenant_item = schema["properties"]["config"]["properties"]["tenants"]["properties"]["tenants"][
        "items"
    ]

    assert "duckdb_schema" not in tenant_item["required"]
    assert "Ignored" in tenant_item["properties"]["duckdb_schema"]["description"]


def test_chart_defaults_use_structured_api_keys_and_tenants():
    values = _load_yaml(PROJECT_ROOT / "helm" / "agentflow" / "values.yaml")

    api_keys = values["secrets"]["apiKeys"]
    tenants = values["config"]["tenants"]

    assert isinstance(api_keys, dict)
    assert isinstance(tenants, dict)
    assert tenants["tenants"]
    assert api_keys["keys"] == []

    for tenant in tenants["tenants"]:
        assert tenant["id"]
        assert tenant["display_name"]
        assert tenant["kafka_topic_prefix"]
        assert tenant["max_events_per_day"] >= 1
        assert tenant["max_api_keys"] >= 1
        # The chart must not ship an example of a field the runtime ignores.
        assert "duckdb_schema" not in tenant


def test_chart_defaults_do_not_embed_production_shaped_api_key_hashes():
    values_text = (PROJECT_ROOT / "helm" / "agentflow" / "values.yaml").read_text(encoding="utf-8")
    values = yaml.safe_load(values_text)

    assert values["secrets"]["apiKeys"]["keys"] == []
    assert "$2b$" not in values_text
    assert "$2a$" not in values_text


def test_helm_template_rejects_persistent_duckdb_multi_replica_render():
    result = _run_helm_template(
        "--set",
        "persistence.enabled=true",
        "--set",
        "autoscaling.enabled=false",
        "--set",
        "replicaCount=2",
    )

    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "DuckDB persistence requires a single writer replica" in output


def test_helm_template_uses_existing_secret_without_rendering_api_key_material():
    result = _run_helm_template(
        "--set",
        "secrets.create=false",
        "--set",
        "secrets.existingSecret=agentflow-api-runtime-secret",
    )

    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "kind: Secret" not in output
    assert "secretName: agentflow-api-runtime-secret" in output


def test_staging_overrides_use_structured_api_keys_with_explicit_ids():
    # The tracked values-staging.yaml carries placeholders (no plaintext keys —
    # see audit p2_2 #5 / p9 #4). The structured contract is enforced by
    # values-staging.yaml.example, which represents the schema operators must
    # populate from a secrets manager before deploying.
    values = _load_yaml(PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml.example")

    api_keys = values["secrets"]["apiKeys"]

    assert isinstance(api_keys, dict)
    assert api_keys["keys"]

    for item in api_keys["keys"]:
        assert item["key_id"]
        assert item["name"]
        assert item["tenant"]
        assert item["created_at"]
        assert item["rate_limit_rpm"] >= 1
        assert item.get("key") or item.get("key_hash")


def test_serving_defaults_to_safe_duckdb_profile_with_clickhouse_support():
    """ADR 0006/0007/0009: the chart's default stays the single-node DuckDB
    profile (the chart ships no ClickHouse service), but ClickHouse serving is
    first-class via values — flipping the backend must wire the env without
    editing templates."""
    values = _load_yaml(CHART_PATH / "values.yaml")

    assert values["serving"]["backend"] == "duckdb"
    assert values["replicaCount"] == 1
    assert values["autoscaling"]["enabled"] is False

    result = _run_helm_template()
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert 'value: "duckdb"' in output
    assert "CLICKHOUSE_HOST" not in output


def test_serving_clickhouse_render_wires_env_and_requires_host():
    rendered = _run_helm_template(
        "--set",
        "serving.backend=clickhouse",
        "--set",
        "serving.clickhouse.host=clickhouse.data.svc",
        "--set",
        "serving.clickhouse.existingSecret=agentflow-clickhouse",
    )
    output = _combined_output(rendered)
    assert rendered.returncode == 0, output
    assert 'value: "clickhouse"' in output
    assert 'value: "clickhouse.data.svc"' in output
    assert "CLICKHOUSE_PASSWORD" in output
    assert 'name: "agentflow-clickhouse"' in output

    missing_host = _run_helm_template("--set", "serving.backend=clickhouse")
    assert missing_host.returncode != 0
    assert "serving.clickhouse.host is required" in _combined_output(missing_host)


def test_chart_control_plane_store_defaults_embedded_and_admits_postgres():
    """ADR 0009/0010: the control plane (webhook queue/log, alert rules+history,
    outbox, dead-letter, usage) defaults to embedded per-pod state. The schema
    enum was a fail-closed ratchet — 'postgres' joined it only once the
    PostgresControlPlaneStore adapter and its chart profile shipped (rollout
    slices 5–6). The default value stays 'embedded' (the zero-dependency demo),
    but 'postgres' is now a first-class, schema-advertised profile."""
    values = _load_yaml(CHART_PATH / "values.yaml")
    assert values["controlPlane"]["store"] == "embedded"
    # The scale-profile DSN is operator-provided (never inlined) — same posture
    # as the ClickHouse password: empty existingSecret by default.
    assert values["controlPlane"]["postgres"]["existingSecret"] == ""
    assert values["controlPlane"]["postgres"]["dsnKey"]

    schema = json.loads((CHART_PATH / "values.schema.json").read_text(encoding="utf-8"))
    assert "controlPlane" in schema["required"]
    control_plane = schema["properties"]["controlPlane"]["properties"]
    assert control_plane["store"]["enum"] == ["embedded", "postgres"]
    postgres = control_plane["postgres"]
    assert postgres["additionalProperties"] is False
    assert "existingSecret" in postgres["required"]
    assert "dsnKey" in postgres["required"]


def test_helm_template_rejects_multi_replica_with_embedded_control_plane():
    """ADR 0009/0010: replicas>1 with per-pod control-plane state is a
    split-brain (duplicate webhook deliveries, forked alert state) even with
    persistence disabled and the serving engine external — the exact hole the
    old persistence-only gate left open."""
    result = _run_helm_template(
        "--set",
        "persistence.enabled=false",
        "--set",
        "replicaCount=2",
        "--set",
        "serving.backend=clickhouse",
        "--set",
        "serving.clickhouse.host=clickhouse.data.svc",
        "--set",
        "serving.clickhouse.existingSecret=agentflow-clickhouse",
    )

    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "control-plane store" in output


def test_helm_template_rejects_autoscaling_with_embedded_control_plane():
    result = _run_helm_template(
        "--set",
        "persistence.enabled=false",
        "--set",
        "autoscaling.enabled=true",
        "--set",
        "autoscaling.maxReplicas=3",
    )

    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "control-plane store" in output


def test_helm_template_single_replica_renders_with_embedded_control_plane():
    """The gate must not touch the default single-replica profile."""
    result = _run_helm_template()
    output = _combined_output(result)
    assert result.returncode == 0, output


def _scale_profile_args(*extra: str) -> list[str]:
    """The minimal set of overrides that satisfies BOTH halves of the ADR
    0010 render gate (external serving engine + external control-plane store),
    so multi-replica / autoscaling is admissible."""
    return [
        "--set",
        "persistence.enabled=false",
        "--set",
        "serving.backend=clickhouse",
        "--set",
        "serving.clickhouse.host=clickhouse.data.svc",
        "--set",
        "serving.clickhouse.existingSecret=agentflow-clickhouse",
        "--set",
        "controlPlane.store=postgres",
        "--set",
        "controlPlane.postgres.existingSecret=agentflow-controlplane-pg",
        *extra,
    ]


def test_embedded_profile_sets_store_env_and_omits_dsn():
    """The default profile still boots embedded: the store env is set
    explicitly (self-documenting manifest) and no PG DSN env is wired."""
    result = _run_helm_template()
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "AGENTFLOW_CONTROLPLANE_STORE" in output
    assert 'value: "embedded"' in output
    assert "AGENTFLOW_CONTROLPLANE_PG_DSN" not in output


def test_postgres_control_plane_profile_wires_store_env_and_dsn_secret():
    """ADR 0010 slice 6: the postgres profile wires AGENTFLOW_CONTROLPLANE_STORE
    and sources AGENTFLOW_CONTROLPLANE_PG_DSN from the operator-provided secret
    (never inlined, mirroring the ClickHouse password)."""
    result = _run_helm_template(*_scale_profile_args("--set", "replicaCount=2"))
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert 'value: "postgres"' in output
    assert "AGENTFLOW_CONTROLPLANE_PG_DSN" in output
    assert 'name: "agentflow-controlplane-pg"' in output
    assert 'key: "controlplane-pg-dsn"' in output


def test_postgres_control_plane_requires_dsn_secret():
    """store=postgres without a DSN secret fails the render (a silent fallback
    to embedded would re-open the split-brain the gate prevents)."""
    result = _run_helm_template(
        "--set",
        "persistence.enabled=false",
        "--set",
        "serving.backend=clickhouse",
        "--set",
        "serving.clickhouse.host=clickhouse.data.svc",
        "--set",
        "serving.clickhouse.existingSecret=agentflow-clickhouse",
        "--set",
        "controlPlane.store=postgres",
        "--set",
        "replicaCount=2",
    )
    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "controlPlane.postgres.existingSecret is required" in output


def test_full_scale_profile_admits_multi_replica():
    """The render gate relaxes automatically once BOTH halves are set: a
    replicaCount=2 render succeeds and schedules two pods."""
    result = _run_helm_template(*_scale_profile_args("--set", "replicaCount=2"))
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "replicas: 2" in output


def test_full_scale_profile_admits_autoscaling_hpa():
    """Phase 3: autoscaling.maxReplicas>1 renders an HPA once the scale profile
    (external serving + external control-plane store) is set."""
    result = _run_helm_template(
        *_scale_profile_args(
            "--set",
            "autoscaling.enabled=true",
            "--set",
            "autoscaling.minReplicas=2",
            "--set",
            "autoscaling.maxReplicas=4",
        )
    )
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "kind: HorizontalPodAutoscaler" in output
    assert "maxReplicas: 4" in output


def test_postgres_store_still_gated_without_clickhouse_backend():
    """The control-plane half alone does not open the gate — multi-replica on
    the duckdb backend must still fail (ADR 0007 engine half unmet)."""
    result = _run_helm_template(
        "--set",
        "persistence.enabled=false",
        "--set",
        "replicaCount=2",
        "--set",
        "controlPlane.store=postgres",
        "--set",
        "controlPlane.postgres.existingSecret=agentflow-controlplane-pg",
    )
    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "Multi-replica requires BOTH" in output


def test_serviceaccount_is_pre_hook_before_provision_job():
    """Live E4 stand (2026-07-16): first helm install hung in pending-install
    because the provision Job (hook weight -5) referenced SA `agentflow` while
    the SA was a normal release resource applied only after hooks. The SA must
    be an earlier pre-install/pre-upgrade hook so install is self-contained.
    """
    rendered = _run_helm_template(
        "--set",
        "serving.backend=clickhouse",
        "--set",
        "serving.clickhouse.host=clickhouse.data.svc",
        "--set",
        "serving.clickhouse.existingSecret=agentflow-clickhouse",
        "--set",
        "provision.enabled=true",
    )
    output = _combined_output(rendered)
    assert rendered.returncode == 0, output

    # Multi-doc YAML: find SA and provision Job hook metadata.
    docs = list(yaml.safe_load_all(rendered.stdout))
    sa_docs = [
        d
        for d in docs
        if d and d.get("kind") == "ServiceAccount"
    ]
    job_docs = [
        d
        for d in docs
        if d
        and d.get("kind") == "Job"
        and str(d.get("metadata", {}).get("name", "")).endswith("-provision")
    ]
    assert len(sa_docs) == 1, "expected exactly one ServiceAccount"
    assert len(job_docs) == 1, "expected provision Job when clickhouse backend"

    sa_ann = sa_docs[0]["metadata"]["annotations"]
    job_ann = job_docs[0]["metadata"]["annotations"]
    assert sa_ann["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert job_ann["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert int(sa_ann["helm.sh/hook-weight"]) < int(job_ann["helm.sh/hook-weight"])
    assert sa_ann["helm.sh/hook-delete-policy"] == "before-hook-creation"
    # Job must still bind the chart SA (not default).
    assert job_docs[0]["spec"]["template"]["spec"]["serviceAccountName"] == sa_docs[0][
        "metadata"
    ]["name"]


def test_serving_clickhouse_tls_render_is_first_class():
    """audit P2-3: TLS to an external ClickHouse must not require extraEnv.
    secure=true flows to CLICKHOUSE_SECURE in BOTH consumers of the wire (API
    deployment and provision job); a private CA secret is mounted read-only
    and CLICKHOUSE_CA_CERT points inside the mount. The profile knob rides
    along so the app-side production gate can be armed from values."""
    rendered = _run_helm_template(
        "--set",
        "serving.backend=clickhouse",
        "--set",
        "serving.clickhouse.host=clickhouse.data.svc",
        "--set",
        "serving.clickhouse.secure=true",
        "--set",
        "serving.clickhouse.tls.caSecret=agentflow-clickhouse-ca",
        "--set",
        "config.profile=production",
    )
    output = _combined_output(rendered)
    assert rendered.returncode == 0, output
    assert output.count('name: CLICKHOUSE_SECURE\n              value: "true"') == 2
    assert output.count("value: /etc/agentflow/tls/clickhouse/ca.crt") == 2
    assert output.count('secretName: "agentflow-clickhouse-ca"') == 2
    assert output.count('value: "production"') == 2

    # The default render stays plaintext-off-by-default and mounts nothing.
    default = _run_helm_template()
    default_output = _combined_output(default)
    assert default.returncode == 0, default_output
    assert "CLICKHOUSE_CA_CERT" not in default_output
    assert "clickhouse-ca" not in default_output
    assert "AGENTFLOW_PROFILE" not in default_output

    # Schema stays strict: the tls block accepts nothing undeclared. The exact
    # message wording belongs to helm's schema validator and changed across
    # helm releases ("Additional property bogus is not allowed" vs
    # "additional properties 'bogus' not allowed"), so assert the meaning,
    # not the phrasing.
    bogus = _run_helm_template("--set", "serving.clickhouse.tls.bogus=1")
    assert bogus.returncode != 0
    bogus_output = _combined_output(bogus)
    assert "bogus" in bogus_output, bogus_output
    assert "additional propert" in bogus_output.lower(), bogus_output
    assert "not allowed" in bogus_output, bogus_output


def test_staging_values_render_with_extra_env_after_redis():
    """Staging overlays set redisUrl + extraEnv; the shared env template must
    not glue the last fixed entry onto the first extraEnv list item (YAML
    'block sequence entries are not allowed in this context')."""
    staging = PROJECT_ROOT / "k8s" / "staging" / "values-staging.yaml"
    result = _run_helm_template("-f", str(staging))
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "AGENTFLOW_WEBHOOKS_FILE" in output
    assert "AGENTFLOW_SEED_ON_BOOT" in output
    # Must be a separate sequence entry, not glued to the REDIS_URL value.
    assert 'value: "redis://' in output
    assert '/0"- name:' not in output


def test_worker_defaults_off_and_omits_process_role():
    """Single-pod shape: no worker Deployment, no AGENTFLOW_PROCESS_ROLE."""
    values = _load_yaml(CHART_PATH / "values.yaml")
    assert values["worker"]["enabled"] is False
    assert values["worker"]["replicaCount"] == 1

    result = _run_helm_template()
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert "AGENTFLOW_PROCESS_ROLE" not in output
    assert "agentflow-worker" not in output
    assert "app.kubernetes.io/component: worker" not in output


def test_worker_enabled_requires_postgres_control_plane():
    result = _run_helm_template("--set", "worker.enabled=true")
    output = _combined_output(result)
    assert result.returncode != 0, output
    assert "worker.enabled requires controlPlane.store=postgres" in output


def test_worker_enabled_splits_api_and_worker_roles():
    """Scale profile + worker: API role=api, worker Deployment role=worker,
    Service selects component=api only (worker not in Service endpoints)."""
    result = _run_helm_template(
        *_scale_profile_args(
            "--set",
            "worker.enabled=true",
            "--set",
            "worker.replicaCount=1",
            "--set",
            "replicaCount=2",
        )
    )
    output = _combined_output(result)
    assert result.returncode == 0, output
    assert (
        "name: agentflow-worker" in output
        or "name: release-name-agentflow-worker" in output
        or "-worker\n" in output
    )
    assert 'name: AGENTFLOW_PROCESS_ROLE\n              value: "api"' in output
    assert 'name: AGENTFLOW_PROCESS_ROLE\n              value: "worker"' in output
    # Service selector narrows to API when worker is on.
    assert "app.kubernetes.io/component: api" in output
    assert "app.kubernetes.io/component: worker" in output
    # Worker must not share the API PVC (RWO multi-attach).
    assert output.count("persistentVolumeClaim:") <= 1
