from importlib.metadata import version

from agentflow import __version__


def test_distribution_version_matches_sdk_version() -> None:
    assert version("agentflow") == __version__ == "1.1.0rc1"
