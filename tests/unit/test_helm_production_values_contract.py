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

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_PATH = PROJECT_ROOT / "helm" / "agentflow"
PRODUCTION_VALUES = CHART_PATH / "values-production.yaml"
CANONICAL_SECURITY = PROJECT_ROOT / "config" / "security.yaml"

# What an environment file owes the production overlay. The overlay itself
# leaves these empty on purpose -- they are the values only the environment
# knows -- so every render here supplies them and then breaks one clause.
_ENVIRONMENT_VALUES = {
    "config": {
        "corsOrigins": "https://app.example.com",
        "trustedProxies": "10.0.0.0/8",
    },
    "ingress": {
        "className": "nginx",
        "hosts": [{"host": "api.example.com", "paths": [{"path": "/", "pathType": "Prefix"}]}],
        "tls": [{"secretName": "agentflow-tls", "hosts": ["api.example.com"]}],
    },
    "secrets": {"existingSecret": "agentflow-production-secret"},
}


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

    values: dict = {key: dict(value) for key, value in _ENVIRONMENT_VALUES.items()}
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

    assert values["config"]["profile"] == "production"
    assert values["networkPolicy"]["enabled"] is True
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
    assert "secrets.existingSecret" in output


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


def test_production_render_drops_the_proxy_clause_without_ingress(tmp_path: Path):
    """TLS in a gateway ahead of the chart is a legitimate shape: with ingress
    off, neither the TLS nor the trusted-proxy clause has anything to say."""
    result = _render(
        tmp_path,
        {"ingress": {"enabled": False, "tls": []}, "config": {"trustedProxies": ""}},
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" not in output


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
            "extraEnv": [{"name": "AGENTFLOW_INSECURE_TRANSPORT_OK", "value": "clickhouse"}],
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
    result = _render(tmp_path, {"config": {"redisUrl": "rediss://redis.data.svc:6380/0"}})
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
