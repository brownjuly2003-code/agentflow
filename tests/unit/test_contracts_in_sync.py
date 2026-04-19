from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_contracts_match_pydantic_models() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/generate_contracts.py", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
