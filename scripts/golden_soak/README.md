# Golden 4-hour soak source pack

This directory tracks the eight byte-exact files from source identity
`20260819-07`. `MANIFEST.json` records their provenance, byte sizes, and
SHA-256 digests. The files are a source reference only; their Kubernetes job
manifests are not a Docker Compose runtime contract.

The root Compose overlay is a **separate capacity-independent**
traffic/exactness/Flink-quiet gate. It **does not close** the Mac
kind/operator/HA/rollback golden-soak gate.

This foundation contains no CI workflow, runtime adapter, lifecycle control,
or result publisher. Consequently, it **cannot emit a soak PASS**. Those
capabilities require separately reviewed implementation slices before this
foundation may be used as a soak acceptance gate.

Validate only the merged Compose model with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.flink.yml -f docker-compose.soak.yml config --quiet
```

Do not infer a runtime PASS from successful configuration validation.
