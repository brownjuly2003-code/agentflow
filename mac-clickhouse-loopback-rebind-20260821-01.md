# macOS ClickHouse loopback rebind

## Goal

Replace the protected ClickHouse runtime with one exact-image container that
publishes `8123` to both macOS loopback and the existing VM/workload address,
while preserving the data volume and a ready rollback path.

## Tasks

- [x] Inventory exact container, image, volume, network, health, and route state.
- [x] Validate the bounded rebind script and its automatic rollback branch.
- [x] Stop the old container, copy its data volume, and start one fresh dual-bind container.
- [x] Verify container health, data aggregate, macOS route, workload route, and rollback readiness.
- [x] Record evidence and update durable state.

## Done When

- [x] New container is healthy with restart count `0` and an exact immutable image ID.
- [x] `127.0.0.1:8123` and `172.18.0.1:8123` both return `SELECT 1` from their intended viewpoints.
- [x] The pre/post `agentflow` table-count and total-row aggregate is unchanged.
- [x] The old exact container remains stopped and disconnected as the immediate rollback object.
- [x] A host-side volume copy and terminal evidence exist under the fresh attempt identity.

## Rollback

On any failure, remove only the newly created container, reconnect the old
exact container to its original network and IP/aliases, start it, and require
healthy state plus the workload-route probe. Never delete the named data
volume or the host-side backup.
