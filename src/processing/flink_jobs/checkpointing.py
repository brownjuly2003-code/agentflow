from __future__ import annotations

import os
from typing import Any


def _checkpoint_constants() -> tuple[object, object]:
    try:
        from pyflink.datastream import CheckpointingMode
        from pyflink.datastream.checkpoint_config import ExternalizedCheckpointCleanup
    except ModuleNotFoundError:
        return "EXACTLY_ONCE", "RETAIN_ON_CANCELLATION"

    return (
        CheckpointingMode.EXACTLY_ONCE,
        ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION,
    )


def configure_checkpointing(env: Any) -> None:
    checkpoint_mode, cleanup_mode = _checkpoint_constants()

    env.enable_checkpointing(60_000)
    config = env.get_checkpoint_config()
    config.set_checkpointing_mode(checkpoint_mode)
    config.set_min_pause_between_checkpoints(30_000)
    config.set_checkpoint_timeout(120_000)
    config.set_max_concurrent_checkpoints(1)
    config.enable_externalized_checkpoints(cleanup_mode)
    config.set_checkpoint_storage(
        os.getenv("FLINK_CHECKPOINT_DIR", "file:///tmp/flink-checkpoints")
    )
