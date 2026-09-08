"""Production ingress must not route unauthenticated /metrics (audit F-10).

The API mounts Prometheus `/metrics` without auth so in-cluster scrape through
the ClusterIP Service keeps working. A `config.profile=production` Ingress that
would send `/metrics` to the API is therefore a values-file defect, not an
application one: the production contract refuses it, and the documented public
prefixes must cover every other route so a new router cannot silently 404.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from tests.unit.test_helm_production_values_contract import (
    _ENVIRONMENT_VALUES,
    CHART_PATH,
    PRODUCTION_VALUES,
    PROJECT_ROOT,
    _output,
    _render,
)

DEPLOYMENT_DOC = PROJECT_ROOT / "docs" / "deployment.md"
_PREFIX_SECTION = "## Production ingress and `/metrics`"
_HELM = shutil.which("helm")
requires_helm = pytest.mark.skipif(
    _HELM is None, reason="helm CLI is required for Helm render policy tests"
)


# Schema-valid Prefix path that, when interpolated unquoted, injects a second
# Ingress rule for unauthenticated /metrics. Reproduced against the production
# fixture: helm exited 0 and the manifest contained both path: /v1 and path: /metrics.
_INJECTED_METRICS_PATH = (
    "/v1\n"
    "            pathType: Prefix\n"
    "            backend:\n"
    "              service:\n"
    "                name: agentflow\n"
    "                port:\n"
    "                  number: 8000\n"
    "          - path: /metrics"
)

# Schema-valid className that, when interpolated unquoted, injects
# spec.defaultBackend pointing at the AgentFlow Service. Kubernetes then
# sends unmatched /metrics to that backend. Reproduced: production
# `helm template` exited 0 with spec.defaultBackend.service.port.number = 8000.
_INJECTED_CLASS_NAME = (
    "nginx\n"
    "  defaultBackend:\n"
    "    service:\n"
    "      name: agentflow\n"
    "      port:\n"
    "        number: 8000"
)

INGRESS_TEMPLATE = CHART_PATH / "templates" / "ingress.yaml"

# Schema types service.port as integer. Quoting it would change the rendered
# YAML type from number to string, so this is the only unquoted interpolation
# permitted in ingress.yaml.
_UNQUOTED_VALUE_EXCEPTIONS = frozenset({"$.Values.service.port"})

_HELM_ACTION = re.compile(r"\{\{-?\s*(.*?)\s*-?\}\}", re.DOTALL)
_CONTROL_ACTION = re.compile(r"^(if|else|end|with|range|define|block)\b")
_VALUES_REF = re.compile(r"\$?\.Values\.[A-Za-z0-9_.]+")
_INGRESS_VALUES_REF = re.compile(r"\$?\.Values\.ingress\b")
_SAFE_PIPE = re.compile(r"(?:^toYaml\b|\|\s*(?:quote|toYaml)\b)")
# include/template emit chart-authored YAML only when handed the chart root.
# A helper handed an ingress field is still user-controlled.
_CHART_AUTHORED = re.compile(r'^(?:include|template)\s+"[^"]+"\s+[.$]\s*$')
_ASSIGNMENT_ACTION = re.compile(r"^\$([A-Za-z0-9_]+)\s*:?=\s*(.*)$", re.DOTALL)
_HELM_VAR = re.compile(r"\$([A-Za-z0-9_]+)\b")
_REBIND_KEYWORDS = frozenset({"with", "range"})
_PUSH_KEYWORDS = frozenset({"if", "with", "range", "define", "block"})
_IN_CLUSTER_ONLY = ("/metrics", "/health/live", "/health/ready")
_PRODUCTION_HIDDEN = ("/docs", "/redoc", "/openapi.json")


def _ingress_documents(stdout: str) -> list[dict]:
    """Ingress objects from helm stdout YAML, ignoring fail text on stderr."""
    if not stdout.strip():
        return []
    try:
        documents = list(yaml.safe_load_all(stdout))
    except yaml.YAMLError:
        return []
    ingresses: list[dict] = []
    for doc in documents:
        if isinstance(doc, dict) and doc.get("kind") == "Ingress":
            ingresses.append(doc)
    return ingresses


def _ingress_rule_paths(stdout: str) -> list[str]:
    """Path values of rendered Ingress objects in helm stdout, not fail text."""
    paths: list[str] = []
    for doc in _ingress_documents(stdout):
        for rule in (doc.get("spec") or {}).get("rules") or []:
            http = rule.get("http") if isinstance(rule, dict) else None
            for entry in (http or {}).get("paths") or []:
                if isinstance(entry, dict) and "path" in entry:
                    paths.append(entry["path"])
    return paths


def _ingress_default_backends(stdout: str) -> list[object]:
    """spec.defaultBackend values of rendered Ingress objects in helm stdout."""
    backends: list[object] = []
    for doc in _ingress_documents(stdout):
        spec = doc.get("spec") if isinstance(doc.get("spec"), dict) else {}
        if "defaultBackend" in spec:
            backends.append(spec["defaultBackend"])
    return backends


def _helm_actions(source: str) -> list[str]:
    return [match.group(1).strip() for match in _HELM_ACTION.finditer(source)]


def _dot_is_ingress(stack: list[tuple[str, bool]]) -> bool:
    """Whether `.` currently names a value under `.Values.ingress`."""
    for keyword, rooted in reversed(stack):
        if keyword in _REBIND_KEYWORDS:
            return rooted
    return False


def _subject_is_ingress_rooted(subject: str, enclosing_ingress: bool) -> bool:
    """True when a `with`/`range` subject is (or stays) under `.Values.ingress`."""
    expr = subject.strip()
    if ":=" in expr:
        expr = expr.split(":=", 1)[1].strip()
    expr = expr.split("|", 1)[0].strip()
    if _INGRESS_VALUES_REF.search(expr):
        return True
    if not enclosing_ingress:
        return False
    if expr == "$" or expr.startswith("$."):
        return False
    if expr.startswith(".Values.") and not expr.startswith(".Values.ingress"):
        return False
    return True


def _rhs_is_user_value(
    expr: str,
    stack: list[tuple[str, bool]],
    user_value_vars: set[str],
) -> bool:
    """True when an assignment RHS is a user-controlled Helm value."""
    refs = _VALUES_REF.findall(expr)
    if refs:
        return True
    if any(name in user_value_vars for name in _HELM_VAR.findall(expr)):
        return True
    if not _dot_is_ingress(stack):
        return False
    core = expr.split("|", 1)[0].strip()
    if core == "$" or core.startswith("$."):
        return False
    if core.startswith("$"):
        return False
    return core == "." or "." in core


def _analyze_ingress_interpolations(source: str) -> tuple[list[str], set[str]]:
    """Walk Helm actions; flag user-controlled ingress interpolations lacking quote/toYaml.

    Scope-aware: `with`/`range` whose subject is rooted at `.Values.ingress`
    (directly, or because the enclosing rebinding scope already is) make every
    interpolating action user-controlled — a bare `.`, `.anything`, `.a.b` —
    without enumerating field names. Outside those scopes, every explicit
    `.Values.*` / `$.Values.*` ref is checked the same way.
    """
    unquoted: list[str] = []
    seen_exceptions: set[str] = set()
    stack: list[tuple[str, bool]] = []
    user_value_vars: set[str] = set()

    for action in _helm_actions(source):
        if action.startswith("/*"):
            continue

        control = _CONTROL_ACTION.match(action)
        if control is not None:
            keyword = control.group(1)
            if keyword == "end":
                if stack:
                    stack.pop()
            elif keyword in _PUSH_KEYWORDS:
                if keyword in _REBIND_KEYWORDS:
                    rooted = _subject_is_ingress_rooted(
                        action[control.end() :],
                        _dot_is_ingress(stack),
                    )
                    stack.append((keyword, rooted))
                else:
                    stack.append((keyword, False))
            continue

        assigned = _ASSIGNMENT_ACTION.match(action)
        if assigned is not None:
            name, expr = assigned.group(1), assigned.group(2)
            if _rhs_is_user_value(expr, stack, user_value_vars):
                user_value_vars.add(name)
            else:
                user_value_vars.discard(name)
            continue

        if _CHART_AUTHORED.match(action):
            continue

        refs = _VALUES_REF.findall(action)
        if refs and all(ref in _UNQUOTED_VALUE_EXCEPTIONS for ref in refs):
            if _SAFE_PIPE.search(action) is not None:
                unquoted.append(action)
            else:
                seen_exceptions.update(refs)
            continue

        user_controlled = (
            _dot_is_ingress(stack)
            or bool(refs)
            or any(name in user_value_vars for name in _HELM_VAR.findall(action))
        )
        if user_controlled and _SAFE_PIPE.search(action) is None:
            unquoted.append(action)

    return unquoted, seen_exceptions


def _unquoted_ingress_interpolations(source: str) -> list[str]:
    """Interpolating actions that emit a user-controlled ingress value unquoted."""
    unquoted, _seen = _analyze_ingress_interpolations(source)
    return unquoted


def _documented_public_prefixes() -> tuple[str, ...]:
    text = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(_PREFIX_SECTION)}\n.*?```(?:[^\n]*)\n(.*?)```",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, (
        "docs/deployment.md must list the public ingress prefixes in a fenced "
        f"block under {_PREFIX_SECTION!r}"
    )
    prefixes = tuple(line.strip() for line in match.group(1).splitlines() if line.strip())
    assert prefixes, "the public-prefix fenced block must not be empty"
    return prefixes


def _prefix_matches(ingress_path: str, request_path: str) -> bool:
    """Kubernetes `pathType: Prefix` matching at a path-segment boundary."""
    if ingress_path == "/":
        return True
    trimmed = ingress_path.rstrip("/") or "/"
    return request_path == trimmed or request_path.startswith(trimmed + "/")


def _would_route_metrics(ingress_path: str) -> bool:
    trimmed = ingress_path.rstrip("/") or "/"
    return trimmed == "/" or trimmed == "/metrics" or trimmed.startswith("/metrics/")


def _iter_app_paths() -> Iterator[str]:
    from agentflow_runtime.serving.api.main import app

    def walk(routes: list, prefix: str) -> Iterator[str]:
        for route in routes:
            context = getattr(route, "include_context", None)
            original = getattr(route, "original_router", None)
            if context is not None and original is not None:
                yield from walk(
                    original.routes,
                    prefix + (getattr(context, "prefix", "") or ""),
                )
                continue
            path = prefix + getattr(route, "path", "")
            if path:
                yield path
            app_obj = getattr(route, "app", None)
            inner = getattr(app_obj, "routes", None) if app_obj is not None else None
            if inner is not None:
                yield from walk(inner, path)

    yield from walk(app.routes, "")


def test_documented_prefixes_cover_production_routes_only() -> None:
    prefixes = _documented_public_prefixes()
    for prefix in prefixes:
        assert not _would_route_metrics(prefix), (
            f"documented prefix {prefix!r} would match unauthenticated /metrics"
        )
        for in_cluster in _IN_CLUSTER_ONLY:
            assert not _prefix_matches(prefix, in_cluster), (
                f"documented prefix {prefix!r} would match in-cluster-only {in_cluster!r}"
            )
        for hidden in _PRODUCTION_HIDDEN:
            assert not _prefix_matches(prefix, hidden), (
                f"documented prefix {prefix!r} would publish production-hidden {hidden!r}"
            )

    fixture_paths = [
        entry["path"] for host in _ENVIRONMENT_VALUES["ingress"]["hosts"] for entry in host["paths"]
    ]
    assert fixture_paths == list(prefixes)

    uncovered: list[str] = []
    for path in _iter_app_paths():
        if any(_prefix_matches(in_cluster, path) for in_cluster in _IN_CLUSTER_ONLY):
            continue
        if any(_prefix_matches(hidden, path) for hidden in _PRODUCTION_HIDDEN):
            continue
        if not any(_prefix_matches(prefix, path) for prefix in prefixes):
            uncovered.append(path)
    assert uncovered == [], (
        "every public FastAPI route must be covered by the documented ingress "
        f"prefixes; uncovered: {uncovered}"
    )


@requires_helm
def test_production_render_refuses_a_root_prefix_path(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/", "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics" in output
    assert "api.example.com" in output
    assert "unauthenticated" in output


@requires_helm
def test_production_render_accepts_enumerated_public_prefixes(tmp_path: Path) -> None:
    result = _render(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" in output
    assert 'ingressClassName: "nginx"' in output
    assert _ingress_default_backends(result.stdout) == []
    for prefix in _documented_public_prefixes():
        assert f'path: "{prefix}"' in output


@requires_helm
def test_production_render_refuses_implementation_specific_path_type(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/v1", "pathType": "ImplementationSpecific"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics" in output
    assert "ImplementationSpecific" in output
    assert "api.example.com" in output


def test_would_route_metrics_models_the_mounted_subtree() -> None:
    """The Prometheus mount serves exposition data at every descendant of /metrics."""
    assert _would_route_metrics("/") is True
    assert _would_route_metrics("/metrics") is True
    assert _would_route_metrics("/metrics/") is True
    assert _would_route_metrics("/metrics/foo") is True
    assert _would_route_metrics("/metrics/foo/") is True
    assert _would_route_metrics("/metrics/a/b") is True
    assert _would_route_metrics("/metricsfoo") is False
    assert _would_route_metrics("/v1") is False


@requires_helm
def test_production_render_refuses_an_explicit_metrics_path(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/metrics", "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics" in output
    assert "api.example.com" in output


@requires_helm
def test_production_render_refuses_an_exact_metrics_path(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/metrics", "pathType": "Exact"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics" in output
    assert "api.example.com" in output


@requires_helm
def test_production_render_accepts_exact_root_path(tmp_path: Path) -> None:
    """Exact `/` matches only `/` and cannot reach the `/metrics` mount."""
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/", "pathType": "Exact"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" in output
    assert 'path: "/"' in output
    assert 'pathType: "Exact"' in output
    assert _ingress_default_backends(result.stdout) == []
    assert _ingress_rule_paths(result.stdout) == ["/"]


@requires_helm
def test_production_render_refuses_metrics_subtree_prefix(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/metrics/foo", "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics/foo" in output
    assert "api.example.com" in output
    assert "unauthenticated" in output


@requires_helm
def test_production_render_refuses_metrics_subtree_exact(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/metrics/foo", "pathType": "Exact"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics/foo" in output
    assert "api.example.com" in output


@requires_helm
def test_production_render_accepts_metricsfoo_prefix(tmp_path: Path) -> None:
    """`/metricsfoo` is a different path segment, not the Prometheus mount."""
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/metricsfoo", "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" in output
    assert 'path: "/metricsfoo"' in output


@requires_helm
def test_production_render_refuses_omitted_path_type(tmp_path: Path) -> None:
    """Missing pathType is fail-closed: the chart cannot prove /metrics is off Ingress.

    values.schema.json requires pathType, so this render skips schema validation
    to exercise the production-contract clause itself.
    """
    helm = shutil.which("helm")
    assert helm is not None

    # `dict(value)` on the list-shaped extraEnv silently yields the map
    # {'name': 'valueFrom'} -- dict() reads each entry's keys as a pair --
    # and the render then fails on the wrong clause entirely.
    values: dict = {
        key: dict(value) if isinstance(value, dict) else list(value)
        for key, value in _ENVIRONMENT_VALUES.items()
    }
    values["ingress"] = dict(values["ingress"])
    values["ingress"]["hosts"] = [
        {"host": "api.example.com", "paths": [{"path": "/"}]},
    ]
    environment = tmp_path / "values-environment.yaml"
    environment.write_text(yaml.safe_dump(values), encoding="utf-8")
    result = subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--values",
            str(PRODUCTION_VALUES),
            "--values",
            str(environment),
            "--skip-schema-validation",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "/metrics" in output
    assert "api.example.com" in output
    assert "pathType" in output
    assert "cannot prove" in output


@requires_helm
def test_dev_profile_default_render_still_accepts_a_root_prefix() -> None:
    helm = shutil.which("helm")
    assert helm is not None
    result = subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--set",
            "ingress.enabled=true",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" in output
    assert 'path: "/"' in output


@requires_helm
def test_production_render_refuses_multiline_path_before_injected_metrics_rule(
    tmp_path: Path,
) -> None:
    """A newline in path used to become a second Ingress rule for /metrics."""
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": _INJECTED_METRICS_PATH, "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "api.example.com" in output
    assert "canonical single-line absolute path" in output


@requires_helm
def test_production_render_refuses_a_path_containing_cr(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": "/v1\r", "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "api.example.com" in output
    assert "canonical single-line absolute path" in output


@requires_helm
@pytest.mark.parametrize("path", ["/ ", "/v1?debug=true"])
def test_production_render_refuses_a_noncanonical_path(tmp_path: Path, path: str) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [{"path": path, "pathType": "Exact"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "api.example.com" in output
    assert "canonical single-line absolute path" in output


@requires_helm
def test_production_render_refuses_an_ingress_host_without_paths(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com",
                        "paths": [],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "api.example.com" in output
    assert "paths" in output
    assert "route nothing" in output


def test_ingress_template_quotes_every_user_controlled_scalar() -> None:
    """R3: a field added to ingress.yaml without quote/toYaml fails here.

    Control actions (`if`/`with`/`range`/`end`) may read `.Values.ingress.*`
    unquoted because they emit no YAML. Every interpolating action in an
    ingress-rooted `with`/`range` (and every explicit `.Values.*` ref)
    must pipe through `quote` or `toYaml`, except the schema-typed integer port.
    """
    source = INGRESS_TEMPLATE.read_text(encoding="utf-8")
    unquoted, seen_exceptions = _analyze_ingress_interpolations(source)
    assert unquoted == [], (
        "every user-controlled scalar interpolated in "
        "helm/agentflow/templates/ingress.yaml must pipe through quote or "
        f"toYaml (or be the integer exception {_UNQUOTED_VALUE_EXCEPTIONS}); "
        f"unquoted: {unquoted}"
    )
    assert seen_exceptions == set(_UNQUOTED_VALUE_EXCEPTIONS), (
        "ingress.yaml must interpolate the integer exception unquoted: "
        f"expected {_UNQUOTED_VALUE_EXCEPTIONS}, saw {seen_exceptions}"
    )
    assert _unquoted_ingress_interpolations(source) == []


def test_unquoted_ingress_analyzer_flags_in_memory_template_mutations() -> None:
    """R3 coverage is self-proving: mutated copies of the template text fail here.

    Mutations are `str.replace` on the in-memory source; the working tree is
    not written.
    """
    source = INGRESS_TEMPLATE.read_text(encoding="utf-8")
    assert _unquoted_ingress_interpolations(source) == []

    stripped_toyaml = source.replace("{{- toYaml . | nindent 4 }}", "{{- . | nindent 4 }}")
    assert stripped_toyaml != source
    stripped_flags = _unquoted_ingress_interpolations(stripped_toyaml)
    assert stripped_flags.count(". | nindent 4") == 2, stripped_flags

    unquoted_class = source.replace(
        ".Values.ingress.className | quote",
        ".Values.ingress.className",
    )
    assert unquoted_class != source
    class_flags = _unquoted_ingress_interpolations(unquoted_class)
    assert ".Values.ingress.className" in class_flags, class_flags

    unquoted_path = source.replace(".path | quote", ".path")
    assert unquoted_path != source
    path_flags = _unquoted_ingress_interpolations(unquoted_path)
    assert ".path" in path_flags, path_flags

    with_new_field = source.replace(
        "pathType: {{ .pathType | quote }}",
        "pathType: {{ .pathType | quote }}\n            extra: {{ .newIngressField }}",
    )
    assert with_new_field != source
    new_field_flags = _unquoted_ingress_interpolations(with_new_field)
    assert ".newIngressField" in new_field_flags, new_field_flags

    extra_port = source.replace(
        "number: {{ $.Values.service.port }}",
        "number: {{ $.Values.service.port }}\n                  also: {{ $.Values.service.port }}",
    )
    assert extra_port != source
    assert _unquoted_ingress_interpolations(extra_port) == []

    include_path = source.replace(
        "path: {{ .path | quote }}",
        'path: {{ include "agentflow.somehelper" .path }}',
    )
    assert include_path != source
    include_flags = _unquoted_ingress_interpolations(include_path)
    assert any('include "agentflow.somehelper" .path' in flag for flag in include_flags), (
        include_flags
    )

    assigned_only = source.replace(
        "{{- range .paths }}",
        "{{- $p := .path }}\n          {{- range .paths }}",
    )
    assert assigned_only != source
    assert _unquoted_ingress_interpolations(assigned_only) == []

    assigned_unquoted = assigned_only.replace("path: {{ .path | quote }}", "path: {{ $p }}")
    assert assigned_unquoted != assigned_only
    assigned_flags = _unquoted_ingress_interpolations(assigned_unquoted)
    assert any(flag == "$p" or flag.endswith("$p") for flag in assigned_flags), assigned_flags

    assigned_quoted = assigned_only.replace(
        "path: {{ .path | quote }}",
        "path: {{ $p | quote }}",
    )
    assert assigned_quoted != assigned_only
    assert _unquoted_ingress_interpolations(assigned_quoted) == []


def test_unquoted_ingress_analyzer_flags_values_outside_ingress_scope() -> None:
    source = INGRESS_TEMPLATE.read_text(encoding="utf-8")
    with_root_value = source.replace(
        '  name: {{ include "agentflow.fullname" . }}',
        '  name: {{ include "agentflow.fullname" . }}\n  suffix: {{ .Values.nameOverride }}',
    )

    assert with_root_value != source
    flags = _unquoted_ingress_interpolations(with_root_value)
    assert ".Values.nameOverride" in flags, flags
    assert all('include "agentflow.fullname" .' not in flag for flag in flags), flags


@requires_helm
def test_production_render_refuses_multiline_ingress_class_name(tmp_path: Path) -> None:
    """A newline in className used to inject spec.defaultBackend for /metrics."""
    result = _render(
        tmp_path,
        {"ingress": {"className": _INJECTED_CLASS_NAME}},
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "ingress.className" in output


@requires_helm
def test_production_render_refuses_multiline_ingress_host(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "ingress": {
                "hosts": [
                    {
                        "host": "api.example.com\n  extra: injected",
                        "paths": [{"path": "/v1", "pathType": "Prefix"}],
                    }
                ]
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "ingress.host" in output


@requires_helm
@pytest.mark.parametrize(
    ("ingress", "field"),
    [
        ({"className": "nginx/controller"}, "ingress.className"),
        (
            {
                "hosts": [
                    {
                        "host": "api_example.com",
                        "paths": [{"path": "/v1", "pathType": "Prefix"}],
                    }
                ]
            },
            "ingress.host",
        ),
    ],
    ids=("class-name", "host"),
)
def test_production_render_refuses_noncanonical_ingress_identity(
    tmp_path: Path,
    ingress: dict,
    field: str,
) -> None:
    result = _render(tmp_path, {"ingress": ingress})
    output = _output(result)

    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert field in output
    assert "canonical" in output


@requires_helm
def test_dev_profile_quotes_injected_class_name_and_path(tmp_path: Path) -> None:
    """Quoting is proven at render time under the inert (dev) contract.

    Production `helm template` writes nothing to stdout on `fail`, so a
    negative production case cannot observe that the injected scalar stayed
    one quoted value. Chart defaults leave the contract off.
    """
    helm = shutil.which("helm")
    assert helm is not None
    overlay = tmp_path / "inject.yaml"
    overlay.write_text(
        yaml.safe_dump(
            {
                "ingress": {
                    "className": _INJECTED_CLASS_NAME,
                    "hosts": [
                        {
                            "host": "api.example.com",
                            "paths": [
                                {
                                    "path": _INJECTED_METRICS_PATH,
                                    "pathType": "Prefix",
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--values",
            str(overlay),
            "--set",
            "ingress.enabled=true",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _ingress_default_backends(result.stdout) == []
    assert _ingress_rule_paths(result.stdout) == [_INJECTED_METRICS_PATH]
