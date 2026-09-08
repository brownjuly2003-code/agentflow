"""Contract: the Flink job image does not ship pip.

pip vendors its own dependency set (``pip/_vendor/vendor.txt``) and Trivy
reports those vendored copies as installed packages. msgpack 1.1.2
(GHSA-6v7p-g79w-8964) and setuptools 70.3.0 (CVE-2025-47273) were the image's
last two unwaived HIGH findings and are unfixable in place: no pin changes what
pip vendors, and both advisories have upstream fixes, so neither is waivable
under ``security/trivy-waivers.json``. Removing pip once the venv is built is
the fix, and it is only safe while nothing installs at runtime.

Docker is not available on the Windows development host, so these checks read
the Dockerfile text. The image rebuild plus Trivy proof is the CI ``trivy`` job;
the job actually starting is the CI ``flink-smoke`` job.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = PROJECT_ROOT / "src" / "agentflow_runtime" / "processing" / "flink_jobs" / "Dockerfile"

VENV_PYTHON = "/opt/pyflink-venv/bin/python"
REQUIREMENTS_INSTALL = f"{VENV_PYTHON} -m pip install --no-cache-dir --require-hashes"
PIP_REMOVAL = f"{VENV_PYTHON} -m pip uninstall --yes pip"
IMPORT_CHECK = f'{VENV_PYTHON} -c "import apache_beam, pyflink;'


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_the_runtime_venv_does_not_keep_pip() -> None:
    text = _dockerfile()

    assert text.count(PIP_REMOVAL) == 1


def test_pip_is_removed_after_the_locked_requirements_are_installed() -> None:
    text = _dockerfile()

    install_at = text.index(REQUIREMENTS_INSTALL)
    removal_at = text.index(PIP_REMOVAL)

    assert install_at < removal_at


def test_pip_is_removed_in_the_same_layer_that_installed_it() -> None:
    text = _dockerfile()

    # A removal in a later RUN would leave pip's files in the earlier layer,
    # and an image pulled at that layer still carries the vendored packages.
    venv_run = next(block for block in text.split("\nRUN ") if REQUIREMENTS_INSTALL in block)

    assert PIP_REMOVAL in venv_run


def test_the_venv_is_proven_to_still_import_the_job_stack_after_the_removal() -> None:
    text = _dockerfile()

    removal_at = text.index(PIP_REMOVAL)
    import_at = text.index(IMPORT_CHECK)

    # Without this the build would happily produce an image whose Python
    # environment no longer starts, and the failure would land in flink-smoke
    # (or production) instead of the build.
    assert removal_at < import_at
    assert "StreamExecutionEnvironment" in text[import_at : import_at + 200]


def test_the_reason_pip_cannot_simply_be_upgraded_is_recorded() -> None:
    text = _dockerfile()

    # The next person to reach for "just bump pip" needs the two advisory ids
    # and the reason a waiver is not available for them.
    assert "GHSA-6v7p-g79w-8964" in text
    assert "CVE-2025-47273" in text
    assert "pip/_vendor" in text
