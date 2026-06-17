DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
FAILED_AUTH_WINDOW_SECONDS = 3_600
DEFAULT_ROTATION_GRACE_PERIOD_SECONDS = 86_400

# M-C4 (audit): every hashed API key adds one bcrypt verification to the
# cold-cache worst case of authenticate(). docs/perf/auth-bench-2026-05-26.md
# measured the p95 at bcrypt_rounds=12 crossing the 1100 ms POST load gate
# around N=20; docs/runbooks/auth-401-spike.md records a "<= 10 hashed keys per
# AuthManager" guidance. AuthManager.load() warns past this soft limit so the
# latency cliff is observable in logs instead of living only as runbook prose.
HASHED_KEY_SOFT_LIMIT = 10
