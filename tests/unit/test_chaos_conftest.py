from tests.chaos import conftest as chaos_conftest


def test_pytest_json_metadata_hook_is_optional():
    assert chaos_conftest.pytest_json_runtest_metadata.pytest_impl["optionalhook"] is True
