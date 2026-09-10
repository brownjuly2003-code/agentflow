# Capability: api-key-identity

A key's `key_id` names its rate-limit bucket (`kid:<key_id>`), its usage rows
(`api_usage.key_id`) and the admin views addressed by id. An id that changes
while the key stays the same splits all three.

## Requirement: an environment-configured key has a stable id
A key configured through `AGENTFLOW_API_KEYS` SHALL get a `key_id` derived from
the key itself, so the same key has the same id on every load, every restart and
every replica that runs with the same key-lookup pepper.

### Scenario: same key, two managers
- **GIVEN** `AGENTFLOW_API_KEYS="k1:Support Agent"` and a fixed key-lookup pepper
- **WHEN** two separate `AuthManager` instances load their keys
- **THEN** both give the key the same `key_id`, of the form `default-support-agent-<8 lowercase hex>`

### Scenario: a reload keeps the id and the bucket
- **GIVEN** a loaded environment-configured key
- **WHEN** the manager reloads
- **THEN** the key's `key_id` is unchanged, and so is its rate-limit bucket

### Scenario: different keys under one name get different ids
- **GIVEN** `AGENTFLOW_API_KEYS="k1:bot,k2:bot"`
- **WHEN** the manager loads its keys
- **THEN** the two keys have different `key_id` values

## Requirement: the id never exposes the key
The derived id SHALL come from the peppered key-lookup digest
(`compute_key_lookup`), never from the plaintext key or an unpeppered hash of
it: the id is written to logs, Redis key names, usage rows and admin responses,
and must not let a guessed key be confirmed offline.

### Scenario: the suffix is the lookup digest's prefix
- **GIVEN** an environment key `k1` and key-lookup pepper `P`
- **WHEN** the manager loads it
- **THEN** the `key_id` suffix equals the first 8 characters of `compute_key_lookup("k1", P)`

### Scenario: a different pepper gives a different id
- **GIVEN** the same environment key and two different key-lookup peppers
- **WHEN** one manager loads it under each pepper
- **THEN** the two `key_id` values differ
