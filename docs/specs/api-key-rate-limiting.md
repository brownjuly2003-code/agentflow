# Capability: api-key-rate-limiting

Per-key request budgets enforced by `AuthManager`
(`src/agentflow_runtime/serving/api/auth/manager.py`). The budget shared across
replicas lives in Redis behind `RateLimiter`. The manager also keeps an
in-memory window per bucket: it is the whole of `is_rate_limited()`, and it is
the secondary check in `check_rate_limit()` when the Redis limiter answers
"allowed, full quota" while a Redis handle is live.

## Requirement: a bucket is named by non-secret key identity
The rate-limit bucket of a key SHALL be named `kid:<key_id>` when the key has an
id, and no bucket name SHALL contain a plaintext API key.

### Scenario: key with an id
- **GIVEN** a key whose `key_id` is `acme-support-1a2b3c4d`
- **WHEN** a request authenticated by that key is rate-limited
- **THEN** its bucket is `kid:acme-support-1a2b3c4d`

## Requirement: reloading the key store keeps live windows
Reloading the key configuration — `load()`, a SIGHUP reload, or the reload that
ends every key create, rotate and revoke — SHALL keep the in-memory rate-limit
window of every key that is still configured, and SHALL drop the window of a
key the reload removed. A key whose id changes on every load, a legacy
hash-only entry in a key file the process cannot write (see
[API key identity](api-key-identity.md)), gets a new bucket on every reload, so
its window starts empty.

### Scenario: a full window survives a reload
- **GIVEN** a key with `rate_limit_rpm: 1` that has already made its one request in the current window
- **WHEN** the key store is reloaded and the same key makes another request inside that window
- **THEN** that request is rate-limited

### Scenario: the secondary window survives a reload
- **GIVEN** a Redis limiter that answers "allowed, full quota" with a live handle, and a key with `rate_limit_rpm: 1` that has made its one request
- **WHEN** the key store is reloaded and `check_rate_limit()` is called for the same key inside the window
- **THEN** the answer is not allowed, with zero remaining

### Scenario: a removed key's window is dropped
- **GIVEN** two configured keys that both made a request in the current window
- **WHEN** one of them is removed from the key file and the store is reloaded
- **THEN** the in-memory windows hold the remaining key's bucket and not the removed key's

### Scenario: no plaintext key becomes a window name
- **GIVEN** a plaintext key configured in the key file, which has made a request
- **WHEN** the store is reloaded
- **THEN** no in-memory window is named by that plaintext key, at any point of the reload
