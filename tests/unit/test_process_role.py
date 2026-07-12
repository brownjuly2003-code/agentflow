"""Audit P1-1: ``AGENTFLOW_PROCESS_ROLE`` splits serving from the delivery
loops so API replicas can scale without multiplying background scanners.

The split-role wiring itself (api skips dispatchers/outbox, worker skips the
serving-side caches) needs the postgres control plane and is proven in
``tests/integration/test_control_plane_postgres_live.py``; what belongs here
is the configuration contract: an unknown role and a split role on the
embedded profile must fail the boot loudly, and the default must be the
single-process shape everything else in this suite boots with.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app


def test_invalid_role_fails_the_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_PROCESS_ROLE", "sidecar")
    with pytest.raises(ValueError, match="AGENTFLOW_PROCESS_ROLE"), TestClient(app):
        pass


@pytest.mark.parametrize("role", ["api", "worker"])
def test_split_roles_refuse_the_embedded_profile(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    # On the embedded profile the delivery loops exist nowhere else: an 'api'
    # process would silently deliver nothing, a 'worker' would scan a store
    # nobody shares. Refusing the boot beats both.
    monkeypatch.setenv("AGENTFLOW_PROCESS_ROLE", role)
    monkeypatch.delenv("AGENTFLOW_CONTROLPLANE_STORE", raising=False)
    with pytest.raises(ValueError, match="postgres control plane"), TestClient(app):
        pass


def test_default_role_runs_the_single_process_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTFLOW_PROCESS_ROLE", raising=False)
    with TestClient(app):
        assert app.state.process_role == "all"
        assert app.state.search_index_rebuild_task is not None
        assert app.state.outbox_processor_task is not None
