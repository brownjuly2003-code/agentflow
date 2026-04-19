import os
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis.database import DirectoryBasedExampleDatabase

_EXAMPLE_DB = DirectoryBasedExampleDatabase(
    Path(__file__).resolve().parent / ".hypothesis"
)

settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    database=_EXAMPLE_DB,
)
settings.register_profile(
    "dev",
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    database=_EXAMPLE_DB,
)
settings.load_profile("ci" if os.getenv("CI") else "dev")
