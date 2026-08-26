import pytest

from agentflow_runtime.serving.api.host_loopback_proxy import RelayConfig, load_config


def test_relay_config_is_explicit_and_bounded() -> None:
    config = load_config(
        {
            "HOST_LOOPBACK_PROXY_TARGET": "172.17.0.1",
            "HOST_LOOPBACK_PROXY_RANGE_START": "18080",
            "HOST_LOOPBACK_PROXY_RANGE_END": "18080",
        }
    )

    assert config == RelayConfig(
        listen_host="127.0.0.1",
        target_host="172.17.0.1",
        port_start=18080,
        port_end=18080,
    )


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"HOST_LOOPBACK_PROXY_TARGET": "not-an-ip"},
        {"HOST_LOOPBACK_PROXY_TARGET": "172.17.0.1", "HOST_LOOPBACK_PROXY_RANGE_START": "0"},
        {
            "HOST_LOOPBACK_PROXY_TARGET": "172.17.0.1",
            "HOST_LOOPBACK_PROXY_RANGE_START": "18081",
            "HOST_LOOPBACK_PROXY_RANGE_END": "18080",
        },
        {
            "HOST_LOOPBACK_PROXY_TARGET": "172.17.0.1",
            "HOST_LOOPBACK_PROXY_RANGE_END": "65536",
        },
    ],
)
def test_relay_config_rejects_missing_or_unsafe_values(environment: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        load_config(environment)
