# Capability: api-key-identity

A key's `key_id` names its rate-limit bucket (`kid:<key_id>`), its usage rows
(`api_usage.key_id`) and the admin views addressed by id. An id that changes
while the key stays the same splits all three.

## Requirement: a key without a persisted id has a stable id
A key whose configuration carries no `key_id` SHALL get a `key_id` derived from
the key's identity, so the same key has the same id on every load, every
restart and every replica that runs with the same key-lookup pepper. This
covers every key from `AGENTFLOW_API_KEYS`, and every key-file entry without a
`key_id` — including one in a key file the process cannot write the id back
to, as when the file is mounted read-only.

### Scenario: same environment key, two managers
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

### Scenario: an id-less entry in a read-only key file
- **GIVEN** a key file the process cannot write, holding an entry that has a `key_lookup` and no `key_id`
- **WHEN** two separate `AuthManager` instances load it, and one of them reloads
- **THEN** the entry has the same `key_id` in both managers and after the reload

### Scenario: a writable key file persists the derived id
- **GIVEN** a writable key file holding an entry that has a plaintext `key` and no `key_id`
- **WHEN** the manager loads it
- **THEN** the file on disk now carries the `key_id` the manager uses, and it is the id derived from that key

## Requirement: the id never exposes the key
The derived id SHALL come from the peppered key-lookup digest — the entry's
stored `key_lookup`, or `compute_key_lookup` over its plaintext key — never
from the plaintext key or an unpeppered hash of it: the id is written to logs,
Redis key names, usage rows and admin responses, and must not let a guessed
key be confirmed offline. An entry that has neither a plaintext key nor a
`key_lookup` (a legacy hash-only entry) has nothing to derive from and keeps a
random id.

### Scenario: the suffix is the lookup digest's prefix
- **GIVEN** an environment key `k1` and key-lookup pepper `P`
- **WHEN** the manager loads it
- **THEN** the `key_id` suffix equals the first 8 characters of `compute_key_lookup("k1", P)`

### Scenario: a stored key_lookup is used as it is
- **GIVEN** a key-file entry with `key_lookup: L` and no `key_id`
- **WHEN** the manager loads it
- **THEN** the `key_id` suffix equals the first 8 characters of `L`

### Scenario: a different pepper gives a different id
- **GIVEN** the same environment key and two different key-lookup peppers
- **WHEN** one manager loads it under each pepper
- **THEN** the two `key_id` values differ
