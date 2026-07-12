"""Policy: the standalone API image never bakes in secret-bearing config and
never runs as root (audit P1-4).

`Dockerfile.api` copies the whole `config/` directory with no allowlist.
`.dockerignore` is what keeps `config/api_keys.yaml`, `config/webhooks.yaml`
and `config/tenants.yaml` out of the build context that `COPY` sees — the
same three paths `pyproject.toml` already excludes from the sdist and
`scripts/check_release_artifacts.FORBIDDEN_MEMBER_PATTERNS` already treats as
forbidden release members. Docker is not available on this host, so these
checks are static: they read the Dockerfile/`.dockerignore` text rather than
building an image.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.check_release_artifacts import FORBIDDEN_MEMBER_PATTERNS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile.api"
DOCKERIGNORE_PATH = PROJECT_ROOT / ".dockerignore"

# The literal (non-glob) config/ entries in the shared forbidden-member list:
# the exact three files, not the generic "*secret*"/"**/secrets/**" globs
# that .dockerignore syntax can't express the same way.
SECRET_CONFIG_PATTERNS = [
    pattern
    for pattern in FORBIDDEN_MEMBER_PATTERNS
    if pattern.startswith("config/") and "*" not in pattern
]


def test_shared_secret_config_list_is_not_empty() -> None:
    # Guards the test itself: if FORBIDDEN_MEMBER_PATTERNS ever stops naming
    # literal config/ paths, the tests below would pass on an empty list
    # without checking anything.
    assert SECRET_CONFIG_PATTERNS == [
        "config/api_keys.yaml",
        "config/tenants.yaml",
        "config/webhooks.yaml",
    ]


def test_dockerignore_excludes_every_secret_bearing_config_file() -> None:
    lines = {line.strip() for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines()}
    missing = [pattern for pattern in SECRET_CONFIG_PATTERNS if pattern not in lines]
    assert not missing, f".dockerignore must exclude: {missing}"


def test_dockerfile_api_copies_config_as_a_directory() -> None:
    # The .dockerignore exclusion above only works because config/ is copied
    # wholesale and .dockerignore filters the build context before COPY ever
    # sees it. If this ever becomes a per-file COPY list instead, the
    # .dockerignore guarantee needs re-checking by hand.
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert re.search(r"^COPY\s+config\s+/app/config\s*$", text, flags=re.MULTILINE), (
        "Dockerfile.api must COPY the whole config/ directory so "
        ".dockerignore's exclusion of secret config files applies"
    )


def test_dockerfile_api_never_copies_a_secret_config_file_by_name() -> None:
    # Only COPY/ADD instruction lines matter here — the file's own comments
    # name these three paths on purpose, to explain why they are absent.
    copy_lines = [
        line
        for line in DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip().upper().startswith(("COPY ", "ADD "))
    ]
    offenders = [
        pattern for pattern in SECRET_CONFIG_PATTERNS if any(pattern in line for line in copy_lines)
    ]
    assert not offenders, (
        f"Dockerfile.api must not COPY/ADD secret config paths directly: {offenders}"
    )


def _final_stage_lines() -> list[str]:
    lines = DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
    stage_start_indices = [
        i for i, line in enumerate(lines) if line.strip().upper().startswith("FROM ")
    ]
    assert stage_start_indices, "no FROM instructions found in Dockerfile.api"
    return lines[stage_start_indices[-1] :]


def test_dockerfile_api_final_stage_sets_a_non_root_user() -> None:
    final_stage = _final_stage_lines()
    user_lines = [line for line in final_stage if line.strip().upper().startswith("USER ")]
    assert user_lines, "Dockerfile.api final stage must set a non-root USER (audit P1-4)"

    last_user = user_lines[-1].split(None, 1)[1].strip()
    root_markers = {"root", "root:root", "0", "0:0"}
    assert last_user not in root_markers, f"final USER must not be root, got {last_user!r}"


def test_dockerfile_api_creates_the_user_before_switching_to_it() -> None:
    final_stage = _final_stage_lines()
    user_index = next(
        i for i, line in enumerate(final_stage) if line.strip().upper().startswith("USER ")
    )
    preceding_text = "\n".join(final_stage[:user_index])
    assert "useradd" in preceding_text, (
        "the non-root user must be created (useradd) before the USER instruction switches to it"
    )
