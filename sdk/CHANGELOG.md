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

### Added
- `RetryPolicy` with exponential backoff, jitter, and `Retry-After` support for transient SDK failures
- `CircuitBreaker` and `CircuitOpenError` for repeated backend failure protection in sync and async clients

### Changed
- `AgentFlowClient` and `AsyncAgentFlowClient` now accept optional `retry_policy` and `circuit_breaker` parameters
- Idempotent SDK requests now retry on `429`, `502`, `503`, `504`, and transport failures before surfacing the final error
- Added resilience-focused SDK tests covering retry/backoff and circuit-breaker behavior

## [1.0.0] - 2026-04-11

### Added
- Public `agentflow.__version__` export for runtime version checks
- `agentflow._compat.deprecated` decorator for consistent deprecation warnings
- Backwards compatibility contract tests for the SDK public API surface

### Changed
- Promoted the SDK package version from preview to stable `1.0.0`
- Locked core client constructors, public methods, exception imports, and required order fields with tests

## [0.1.0] - 2026-04-10

### Added
- Initial Python SDK with sync and async clients
- Typed models for entities, health, catalog, and query responses
- CLI entrypoint for common AgentFlow API operations
