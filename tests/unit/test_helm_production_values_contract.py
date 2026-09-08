"""The chart's production posture contract (audit F-11).

Two things are being pinned here, and they are deliberately separate:

* the **dev defaults** stay installable on a laptop cluster -- no NetworkPolicy
  controller, no ingress TLS, an inline Secret -- because that is what makes
  `helm install` a five-second demo;
* **`config.profile=production`** is the operator declaring a production
  release, and from that point the same values file is held to a contract.

Before this contract, the two were the same values file with one string
changed, so a formally successful render could ship dev posture under a
production label. Each negative test below leaves exactly one clause violated,
so the assertion is about that clause and not about which guard happens to fire
first.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = PROJECT_ROOT / "helm" / "agentflow"
PRODUCTION_VALUES = CHART_PATH / "values-production.yaml"
CANONICAL_SECURITY = PROJECT_ROOT / "config" / "security.yaml"
_API_IMAGE_DIGEST = "sha256:" + "b" * 64
# Read from the chart rather than repeated here: the default moved off the
# unclaimed Docker Hub namespace `agentflow/api` (audit FB-08), and a test
# that hardcodes a registry has to be edited every time that judgement is
# revisited.
_DEFAULT_API_REPOSITORY = yaml.safe_load((CHART_PATH / "values.yaml").read_text(encoding="utf-8"))[
    "image"
]["repository"]

# What an environment file owes the production overlay. The overlay itself
# leaves these empty on purpose -- they are the values only the environment
# knows -- so every render here supplies them and then breaks one clause.
# The scrape namespace is one of those: values-production.yaml does not guess
# it, and a render that still has only ingress-nginx is refused.
_ENVIRONMENT_VALUES = {
    "image": {"digest": _API_IMAGE_DIGEST},
    "config": {
        "corsOrigins": "https://app.example.com",
        "trustedProxies": "10.0.0.0/8",
    },
    "networkPolicy": {
        "ingressFromNamespaces": [
            {"kubernetes.io/metadata.name": "ingress-nginx"},
            {"kubernetes.io/metadata.name": "monitoring"},
        ],
        # An egress rule with `ports:` and no `to:` allows that port to every
        # address (audit FB-09), so production must name peers for every rule
        # that renders. Only `kafka` renders under these values: the backend is
        # DuckDB, there is no Redis or OTLP endpoint, the control plane is
        # embedded and the lake materializer is off.
        "egressTo": {"kafka": [{"ipBlock": {"cidr": "10.30.0.0/16"}}]},
    },
    "ingress": {
        "className": "nginx",
        "hosts": [
            {
                "host": "api.example.com",
                "paths": [
                    {"path": "/v1", "pathType": "Prefix"},
                    {"path": "/admin", "pathType": "Prefix"},
                ],
            }
        ],
        "tls": [{"secretName": "agentflow-tls", "hosts": ["api.example.com"]}],
    },
    "secrets": {"existingSecret": "agentflow-production-secret"},
    # Pepper material (audit FB-07, AF-13). Both env vars fall back to
    # constants committed to this repository, and the API refuses to boot on
    # profile=production with either unset -- so a render that omits them
    # installs a workload that cannot start. Projected from the Secret, never
    # written as a literal `value`, for the same reason secrets.create=true is
    # refused: Helm values persist in release metadata and shell history.
    "extraEnv": [
        {
            "name": "AGENTFLOW_KEY_LOOKUP_PEPPER",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "agentflow-production-secret",
                    "key": "key-lookup-pepper",
                }
            },
        },
        {
            "name": "AGENTFLOW_QUERY_FINGERPRINT_PEPPER",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "agentflow-production-secret",
                    "key": "query-fingerprint-pepper",
                }
            },
        },
    ],
}


def _egress_to(**extra: list) -> dict:
    """Baseline egress destinations plus the ones a switched-on feature needs.

    Turning a feature on adds an egress rule, and a rule with no `to:` allows
    its port to every address -- so production asks for peers (audit FB-09).
    Without this, a test about ClickHouse TLS would fail on the egress clause
    instead, which is the opposite of one clause at a time.
    """
    destinations = dict(_ENVIRONMENT_VALUES["networkPolicy"]["egressTo"])
    destinations.update(extra)
    return destinations


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _render(tmp_path: Path, overrides: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Render the chart with the production overlay plus an environment file.

    `overrides` is merged into the environment values one level deep, which is
    enough to break a single clause per test while leaving the rest compliant.
    """
    helm = shutil.which("helm")
    if helm is None:
        raise AssertionError("helm is required for Helm render policy tests")

    values: dict = {
        key: dict(value) if isinstance(value, dict) else list(value)
        for key, value in _ENVIRONMENT_VALUES.items()
    }
    for section, patch in (overrides or {}).items():
        if not isinstance(patch, dict):
            values[section] = patch
            continue
        merged = dict(values.get(section, {}))
        merged.update(patch)
        values[section] = merged

    environment = tmp_path / "values-environment.yaml"
    environment.write_text(yaml.safe_dump(values), encoding="utf-8")
    return subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--values",
            str(PRODUCTION_VALUES),
            "--values",
            str(environment),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _schema_path_reported(output: str, *segments: str) -> bool:
    """Helm's JSON Schema printer names a values path as dotted (`a.b`) or as a
    JSON pointer (`/a/b`), depending on the Helm release. CI installs unpinned
    Helm; both forms are live.
    """
    dotted = ".".join(segments)
    pointer = "/" + "/".join(segments)
    return dotted in output or pointer in output


def test_chart_defaults_match_the_canonical_security_policy():
    """The chart shipped bcrypt and a two-header denylist while the runtime and
    `config/security.yaml` were on argon2id and five headers, so installing the
    chart quietly downgraded the posture the rest of the repo documents."""
    chart_policy = yaml.safe_load(_load_yaml(CHART_PATH / "values.yaml")["config"]["security"])
    canonical = _load_yaml(CANONICAL_SECURITY)

    assert chart_policy["security"]["key_hashing"] == "argon2id"
    assert (
        chart_policy["security"]["sensitive_headers_to_redact"]
        == canonical["security"]["sensitive_headers_to_redact"]
    )


def test_dev_defaults_stay_installable_without_the_production_contract():
    """The contract must not leak into the default install: no profile, no
    NetworkPolicy controller required, inline Secret, localhost CORS."""
    helm = shutil.which("helm")
    assert helm is not None
    result = subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode == 0, output
    defaults = _load_yaml(CHART_PATH / "values.yaml")
    assert defaults["config"]["profile"] == ""
    assert defaults["networkPolicy"]["enabled"] is False
    assert defaults["secrets"]["create"] is True
    assert "kind: NetworkPolicy" not in output
    assert "kind: Secret" in output


def test_production_overlay_ships_no_inline_key_material():
    values = _load_yaml(PRODUCTION_VALUES)

    assert values["image"]["digest"] == ""
    assert values["config"]["profile"] == "production"
    assert values["networkPolicy"]["enabled"] is True
    from_ns = values["networkPolicy"]["ingressFromNamespaces"]
    ns_names = [
        item.get("kubernetes.io/metadata.name") for item in from_ns if isinstance(item, dict)
    ]
    assert "ingress-nginx" in ns_names
    assert ns_names == ["ingress-nginx"]
    assert values["secrets"]["create"] is False
    assert values["secrets"]["existingSecret"] == ""
    assert values["secrets"]["adminKey"] == ""
    assert values["secrets"]["apiKeys"]["keys"] == []
    assert values["serviceAccount"]["name"] == ""
    assert values["serving"]["clickhouse"]["secure"] is True

    text = PRODUCTION_VALUES.read_text(encoding="utf-8")
    assert "$2b$" not in text
    assert "$2a$" not in text


def test_production_overlay_alone_refuses_to_render():
    """Fail-closed: the overlay is half a configuration. On its own it must
    stop the render rather than fall back to a chart default."""
    helm = shutil.which("helm")
    assert helm is not None
    result = subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH), "--values", str(PRODUCTION_VALUES)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode != 0
    assert _schema_path_reported(output, "secrets", "existingSecret")


def test_schema_path_reported_accepts_both_printers_and_rejects_unrelated_output():
    """Negative control: the helper must not match an unrelated refusal string."""
    pointer = "- at '/secrets/existingSecret': minLength: got 0, want 1"
    dotted = "secrets.existingSecret: minLength: got 0, want 1"
    assert _schema_path_reported(pointer, "secrets", "existingSecret")
    assert _schema_path_reported(dotted, "secrets", "existingSecret")
    assert not _schema_path_reported("nothing here", "secrets", "existingSecret")


def test_compliant_production_render_carries_the_declared_posture(tmp_path: Path):
    result = _render(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    assert 'value: "production"' in output
    assert "kind: NetworkPolicy" in output
    # Key material comes from the operator-managed Secret, so the chart renders
    # no Secret of its own and mounts theirs.
    assert "kind: Secret" not in output
    assert "agentflow-production-secret" in output
    assert "name: AGENTFLOW_TRUSTED_PROXIES" in output
    assert 'value: "10.0.0.0/8"' in output
    assert "secretName: agentflow-tls" in output
    assert f'image: "{_DEFAULT_API_REPOSITORY}@{_API_IMAGE_DIGEST}"' in output


def test_production_render_requires_an_immutable_api_image_digest(tmp_path: Path):
    result = _render(tmp_path, {"image": {"digest": ""}})
    output = _output(result)

    assert result.returncode != 0
    assert "image.digest is empty" in output


def test_production_render_reports_every_violation_at_once(tmp_path: Path):
    """One `helm template` round trip per fix would be a bad trade for an
    operator holding an outage; the guard collects the whole set."""
    result = _render(
        tmp_path,
        {"config": {"corsOrigins": "http://localhost:3000", "trustedProxies": ""}},
    )
    output = _output(result)

    assert result.returncode != 0
    assert "config.trustedProxies is empty" in output
    assert "is still the chart's dev default" in output


def test_production_render_requires_network_policy(tmp_path: Path):
    result = _render(tmp_path, {"networkPolicy": {"enabled": False}})
    output = _output(result)

    assert result.returncode != 0
    assert "networkPolicy.enabled=false" in output


def test_production_render_refuses_inline_secrets(tmp_path: Path):
    # The chart schema already pairs create=true with an empty existingSecret,
    # so an operator falling back to the inline Secret leaves it unset; the
    # contract is what refuses the fallback itself.
    result = _render(
        tmp_path,
        {"secrets": {"create": True, "existingSecret": "", "adminKey": "not-a-real-key"}},
    )
    output = _output(result)

    assert result.returncode != 0
    assert "secrets.create=true" in output
    assert "secrets.adminKey is set" in output
    # The refusal must not echo the value it is refusing.
    assert "not-a-real-key" not in output


def test_production_render_requires_ingress_tls(tmp_path: Path):
    result = _render(tmp_path, {"ingress": {"tls": []}})
    output = _output(result)

    assert result.returncode != 0
    assert "empty ingress.tls" in output


def test_production_render_requires_ingress_hosts(tmp_path: Path):
    """An enabled Ingress with no hosts renders rules that route nothing --
    a deploy that reports success and serves no traffic."""
    result = _render(tmp_path, {"ingress": {"hosts": []}})
    output = _output(result)

    assert result.returncode != 0
    assert "no ingress.hosts" in output


def test_production_render_requires_trusted_proxies_behind_ingress(tmp_path: Path):
    result = _render(tmp_path, {"config": {"trustedProxies": ""}})
    output = _output(result)

    assert result.returncode != 0
    assert "config.trustedProxies is empty while ingress is enabled" in output


def test_production_render_drops_the_tls_clause_without_ingress(tmp_path: Path):
    """TLS in a gateway ahead of the chart is a legitimate shape: with ingress
    off the TLS clause has nothing to say. The client-address clause still does
    -- see the two tests below -- so this render answers it."""
    result = _render(
        tmp_path,
        {
            "ingress": {"enabled": False, "tls": []},
            "config": {"trustedProxies": "", "gateway": {"preservesClientIp": True}},
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" not in output


def test_production_render_refuses_an_unanswered_external_gateway(tmp_path: Path):
    """`ingress.enabled=false` used to make the trusted-proxy clause vanish
    rather than answer it. That is the sanctioned production shape, and it is
    exactly the one where every caller reaches the pod through a gateway the
    chart cannot see: the failed-auth throttle and every logged client_ip then
    key on one shared address (audit FB-06). Silence is no longer an answer."""
    result = _render(
        tmp_path,
        {"ingress": {"enabled": False, "tls": []}, "config": {"trustedProxies": ""}},
    )
    output = _output(result)

    assert result.returncode != 0
    assert "config.gateway.preservesClientIp is not set" in output


def test_production_render_accepts_named_gateway_peers(tmp_path: Path):
    """The other way to answer it: name the peers instead of declaring that the
    source address survives."""
    result = _render(
        tmp_path,
        {
            "ingress": {"enabled": False, "tls": []},
            "config": {"trustedProxies": "10.0.0.0/8"},
        },
    )

    assert result.returncode == 0, _output(result)


def test_production_render_refuses_a_cors_wildcard(tmp_path: Path):
    result = _render(tmp_path, {"config": {"corsOrigins": "*"}})
    output = _output(result)

    assert result.returncode != 0
    assert "CORS runs with credentials" in output


def test_production_render_refuses_the_shared_service_account_escape_hatch(tmp_path: Path):
    result = _render(tmp_path, {"serviceAccount": {"name": "agentflow-shared"}})
    output = _output(result)

    assert result.returncode != 0
    assert "legacy escape hatch" in output


def test_production_render_refuses_plaintext_clickhouse(tmp_path: Path):
    result = _render(
        tmp_path,
        {
            "serving": {
                "backend": "clickhouse",
                "clickhouse": {"host": "clickhouse.data.svc", "secure": False},
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "serving.clickhouse.secure=false" in output


def test_production_render_accepts_a_named_plaintext_exemption(tmp_path: Path):
    """The chart must not be stricter than the app: `transport_policy` accepts a
    per-store, greppable opt-out for a deliberate in-cluster plaintext hop, so
    the render does too -- naming the store, not flipping a global switch."""
    result = _render(
        tmp_path,
        {
            "serving": {
                "backend": "clickhouse",
                "clickhouse": {"host": "clickhouse.data.svc", "secure": False},
            },
            # Appended, not substituted: extraEnv is one list, and the
            # production contract also reads the two pepper entries out of it.
            "extraEnv": [
                *_ENVIRONMENT_VALUES["extraEnv"],
                {"name": "AGENTFLOW_INSECURE_TRANSPORT_OK", "value": "clickhouse"},
            ],
            "networkPolicy": {
                "egressTo": _egress_to(clickhouse=[{"ipBlock": {"cidr": "10.30.1.0/24"}}])
            },
        },
    )
    output = _output(result)

    assert result.returncode == 0, output


def test_production_render_refuses_plaintext_redis(tmp_path: Path):
    result = _render(tmp_path, {"config": {"redisUrl": "redis://redis.data.svc:6379/0"}})
    output = _output(result)

    assert result.returncode != 0
    assert "is plaintext" in output


def test_production_render_accepts_tls_redis(tmp_path: Path):
    result = _render(
        tmp_path,
        {
            "config": {"redisUrl": "rediss://redis.data.svc:6380/0"},
            "networkPolicy": {
                "egressTo": _egress_to(redis=[{"ipBlock": {"cidr": "10.30.2.0/24"}}])
            },
        },
    )
    output = _output(result)

    assert result.returncode == 0, output


def test_production_render_reads_the_denylist_case_insensitively(tmp_path: Path):
    """HTTP header names are case-insensitive and the runtime compares them
    lowercased, so the contract must not fail a policy that spells them
    differently -- that would be pedantry dressed as a security check."""
    lowercased = (
        "security:\n"
        "  key_hashing: argon2id\n"
        "  sensitive_headers_to_redact:\n"
        "    - authorization\n"
        "    - x-api-key\n"
        "    - x-admin-key\n"
        "    - cookie\n"
        "    - set-cookie\n"
    )
    result = _render(tmp_path, {"config": {"security": lowercased}})
    output = _output(result)

    assert result.returncode == 0, output


def test_production_render_refuses_a_weakened_security_policy(tmp_path: Path):
    """`config.security` is a free-text blob mounted into the pod, so it is the
    one place a production install can silently return to bcrypt or trim the
    redaction denylist."""
    weakened = (
        "security:\n  key_hashing: bcrypt\n  sensitive_headers_to_redact:\n    - Authorization\n"
    )
    result = _render(tmp_path, {"config": {"security": weakened}})
    output = _output(result)

    assert result.returncode != 0
    assert "key_hashing" in output
    assert "X-Admin-Key" in output
    assert "Set-Cookie" in output


def _extra_env_without(name: str) -> list[dict]:
    return [item for item in _ENVIRONMENT_VALUES["extraEnv"] if item["name"] != name]


@pytest.mark.parametrize(
    "pepper",
    ["AGENTFLOW_KEY_LOOKUP_PEPPER", "AGENTFLOW_QUERY_FINGERPRINT_PEPPER"],
)
def test_production_render_requires_both_peppers(tmp_path: Path, pepper: str):
    """Neither pepper was wired into the chart at all, while the app-side gate
    refuses to boot without them (audit FB-07). A render that omits one is a
    release that installs a workload which cannot start, so the refusal belongs
    where the operator can read it -- at render time, with the name in it."""
    result = _render(tmp_path, {"extraEnv": _extra_env_without(pepper)})
    output = _output(result)

    assert result.returncode != 0
    assert pepper in output
    assert "secretKeyRef" in output


@pytest.mark.parametrize(
    "pepper",
    ["AGENTFLOW_KEY_LOOKUP_PEPPER", "AGENTFLOW_QUERY_FINGERPRINT_PEPPER"],
)
def test_production_render_refuses_pepper_material_written_into_values(tmp_path: Path, pepper: str):
    """A literal `value:` satisfies the app-side gate and defeats the reason
    secrets.create=true is refused: the pepper then lives in Helm release
    metadata and in whatever shell ran the upgrade."""
    extra_env = [*_extra_env_without(pepper), {"name": pepper, "value": "a-real-secret"}]
    result = _render(tmp_path, {"extraEnv": extra_env})
    output = _output(result)

    assert result.returncode != 0
    assert pepper in output
    assert "release metadata" in output


def test_production_render_refuses_a_pepper_from_a_configmap(tmp_path: Path):
    """`valueFrom` is not the point; the Secret is. A ConfigMap is a plaintext
    object every namespace reader can list."""
    extra_env = [
        *_extra_env_without("AGENTFLOW_KEY_LOOKUP_PEPPER"),
        {
            "name": "AGENTFLOW_KEY_LOOKUP_PEPPER",
            "valueFrom": {"configMapKeyRef": {"name": "agentflow-cm", "key": "pepper"}},
        },
    ]
    result = _render(tmp_path, {"extraEnv": extra_env})
    output = _output(result)

    assert result.returncode != 0
    assert "configMapKeyRef" in output


def test_the_compliant_render_projects_both_peppers_into_the_api_container(tmp_path: Path):
    """The clause is only worth having if the values it demands actually reach
    the process the gate runs in."""
    result = _render(tmp_path)
    output = _output(result)
    assert result.returncode == 0, output

    api = next(
        doc
        for doc in yaml.safe_load_all(output)
        if doc and doc.get("kind") == "Deployment" and doc["metadata"]["name"].endswith("agentflow")
    )
    env = {item["name"]: item for item in api["spec"]["template"]["spec"]["containers"][0]["env"]}

    for pepper in ("AGENTFLOW_KEY_LOOKUP_PEPPER", "AGENTFLOW_QUERY_FINGERPRINT_PEPPER"):
        assert "value" not in env[pepper]
        assert env[pepper]["valueFrom"]["secretKeyRef"]["name"] == "agentflow-production-secret"


def test_the_dev_defaults_do_not_ask_for_a_pepper(tmp_path: Path):
    """The gate is production-only on both sides. `helm install` with the chart
    defaults must stay a five-second demo."""
    helm = shutil.which("helm")
    assert helm is not None
    result = subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, _output(result)
    assert "AGENTFLOW_KEY_LOOKUP_PEPPER" not in result.stdout
