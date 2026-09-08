"""The production-shaped local stack must say what it is (audit F-09).

`docker-compose.prod.yml` looks like production -- three brokers, a schema
registry, ClickHouse, tracing, dashboards -- and is not: plaintext transports,
dev credentials, no TLS. The file has always said so in a comment. What made it
an operator trap was everything *around* the comment: a Make target called
`stack-prod`, an API container with no auth settings at all (so every `/v1`
route fail-closed with 503 and only `/health/ready` was ever smoked), and a
Prometheus config written by a heredoc at start-up that loaded no alert rules
and reached no Alertmanager.

These tests pin the corrections. They are deliberately about naming, the auth
contract and the alerting path -- not about the topology, which is fine as it
is.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.prod.yml"
PROMETHEUS_CONFIG = PROJECT_ROOT / "monitoring" / "prometheus" / "prometheus.prod-shaped-local.yml"
ALERTMANAGER_CONFIG = (
    PROJECT_ROOT / "monitoring" / "alerting" / "alertmanager.prod-shaped-local.yml"
)


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _api_environment() -> dict:
    return _compose()["services"]["agentflow-api"]["environment"]


def test_compose_project_name_marks_the_stack_as_a_local_demo():
    """The project name is what `docker compose ps` and every container name
    show, so it is the marking an operator cannot miss. It also stops this
    stack from sharing containers and volumes with the dev compose file, which
    both used to inherit from the directory name."""
    compose = _compose()

    assert compose["name"] == "agentflow-prod-shaped-local"


def test_compose_header_points_at_the_real_production_path():
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    header = text[: text.index("services:")]

    assert "not a production recipe" in header
    assert "values-production.yaml" in header


def test_api_declares_an_explicit_local_auth_contract():
    environment = _api_environment()

    assert environment["AGENTFLOW_API_KEYS_FILE"] == "/app/config/api_keys.yaml"
    assert environment["AGENTFLOW_DEMO_MODE"] == "true"
    assert environment["DEMO_API_KEY"] == "${DEMO_API_KEY:-demo-key}"


def test_api_cannot_claim_the_production_profile():
    """Demo mode is not just convenience here: the runtime refuses
    `AGENTFLOW_DEMO_MODE=true` together with `AGENTFLOW_PROFILE=production`, so
    declaring demo mode is what makes this stack structurally unable to be
    relabelled into a production one."""
    environment = _api_environment()

    assert "AGENTFLOW_PROFILE" not in environment
    assert environment["AGENTFLOW_DEMO_MODE"] == "true"


def test_api_mounts_the_config_directory_the_keys_file_lives_in():
    volumes = _compose()["services"]["agentflow-api"]["volumes"]

    assert "./config:/app/config:ro" in volumes


def test_prometheus_uses_tracked_config_and_rules_not_a_startup_heredoc():
    prometheus = _compose()["services"]["prometheus"]
    volumes = prometheus["volumes"]

    assert "entrypoint" not in prometheus, (
        "the config must not be generated at start-up: it was untracked, "
        "unreviewable and scrape-only"
    )
    assert (
        "./monitoring/prometheus/prometheus.prod-shaped-local.yml:/etc/prometheus/prometheus.yml:ro"
        in volumes
    )
    assert "./monitoring/alerting/rules.yml:/etc/prometheus/rules.yml:ro" in volumes
    assert "scrape_configs" not in COMPOSE_PATH.read_text(encoding="utf-8")


def test_prometheus_config_loads_the_rules_and_reaches_alertmanager():
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))

    assert config["rule_files"] == ["/etc/prometheus/rules.yml"]
    targets = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert targets == ["alertmanager:9093"]
    jobs = {scrape["job_name"] for scrape in config["scrape_configs"]}
    assert "agentflow-api" in jobs


def test_alertmanager_runs_and_admits_that_it_notifies_nobody():
    compose = _compose()
    alertmanager = compose["services"]["alertmanager"]
    config = yaml.safe_load(ALERTMANAGER_CONFIG.read_text(encoding="utf-8"))

    assert (
        "./monitoring/alerting/alertmanager.prod-shaped-local.yml:/etc/alertmanager/alertmanager.yml:ro"
        in alertmanager["volumes"]
    )
    assert compose["services"]["prometheus"]["depends_on"]["alertmanager"]

    # A receiver with no notifier is the honest shape for a local demo; one
    # with a real integration would claim an on-call path that does not exist.
    assert [receiver["name"] for receiver in config["receivers"]] == ["local-sink"]
    assert set(config["receivers"][0]) == {"name"}
    assert config["route"]["receiver"] == "local-sink"


def test_alert_rules_are_the_tracked_ones():
    """The rules mounted here are the repository's own, not a copy that can
    drift."""
    rules = yaml.safe_load(
        (PROJECT_ROOT / "monitoring" / "alerting" / "rules.yml").read_text(encoding="utf-8")
    )

    assert rules["groups"], "the mounted rule file must actually contain rules"


def test_make_target_is_named_for_what_the_stack_is():
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "stack-prod-shaped-local:" in makefile
    assert "stack-prod-shaped-local-smoke:" in makefile
    assert "scripts/compose_prod_shaped_smoke.py" in makefile


def test_old_make_target_refuses_instead_of_silently_starting_the_stack():
    """`stack-prod` kept working would keep the trap: an operator typing the
    old name would get the old, misleading answer."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    body = makefile[makefile.index("\nstack-prod:") :]
    body = body[: body.index("\n\n")]

    assert "docker compose" not in body
    assert "stack-prod-shaped-local" in body
    assert "@exit 1" in body
