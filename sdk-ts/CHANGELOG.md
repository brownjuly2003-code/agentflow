# Changelog

This SDK follows semantic versioning.

SemVer rules:
- `MAJOR`: breaking changes such as removed methods or incompatible parameter changes
- `MINOR`: new methods, optional parameters, or additive model fields
- `PATCH`: bug fixes and internal changes with no public API break

Deprecation policy:
- A method or field is deprecated with a warning for one full major version before removal
- The warning states what is deprecated, what to use instead, and in which version removal happens

## [Unreleased]

### Changed
- `engines.node` floor raised from `>=18` to `>=20` (audit F-11). Node 18 is
  end-of-life and the SDK toolchain (Vitest 4) needs `util.styleText`, which
  Node 18 lacks — CI proved the declared 18 floor was untestable. CI now
  exercises Node 20 (required lane) and 22 (compat lane).

### Added
- `RetryPolicy` with exponential backoff, jitter, and `Retry-After` support for transient SDK failures
- `CircuitBreaker`, `CircuitState`, and `CircuitOpenError` exports for repeated backend failure protection

### Changed
- `AgentFlowClient` now accepts optional `retryPolicy` and `circuitBreaker` options
- Idempotent SDK requests now retry on `429`, `502`, `503`, `504`, and transport failures before surfacing the final error
- Added resilience-focused Vitest coverage for retry/backoff and circuit-breaker behavior

## [1.0.0] - 2026-04-11

### Added
- Stable TypeScript SDK for entity, metric, batch, query, health, and SSE APIs
- Root package exports for the client, public exception types, and response model types
