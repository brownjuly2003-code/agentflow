from __future__ import annotations

import os
from typing import Any


def _checkpoint_constants() -> tuple[object, object]:
    try:
        from pyflink.datastream import CheckpointingMode, ExternalizedCheckpointRetention
    except ModuleNotFoundError:
        return "EXACTLY_ONCE", "RETAIN_ON_CANCELLATION"

    return (
        CheckpointingMode.EXACTLY_ONCE,
        ExternalizedCheckpointRetention.RETAIN_ON_CANCELLATION,
    )


def _checkpoint_dir_configuration() -> Any:
    """Build the checkpoint-directory configuration for ``env.configure``.

    Flink 2.x removed ``CheckpointConfig.set_checkpoint_storage``; the
    checkpoint directory is configured through the
    ``execution.checkpointing.dir`` option instead. Without PyFlink installed
    a plain mapping with the same key is returned so test fakes can assert
    on the configured value.
    """
    checkpoint_dir = os.getenv("FLINK_CHECKPOINT_DIR", "file:///tmp/flink-checkpoints")
    try:
        from pyflink.common import Configuration
    except ModuleNotFoundError:
        return {"execution.checkpointing.dir": checkpoint_dir}

    configuration = Configuration()
    configuration.set_string("execution.checkpointing.dir", checkpoint_dir)
    return configuration


def configure_checkpointing(env: Any) -> None:
    checkpoint_mode, retention_mode = _checkpoint_constants()

    env.enable_checkpointing(60_000)
    config = env.get_checkpoint_config()
    config.set_checkpointing_mode(checkpoint_mode)
    config.set_min_pause_between_checkpoints(30_000)
    config.set_checkpoint_timeout(120_000)
    config.set_max_concurrent_checkpoints(1)
    config.set_externalized_checkpoint_retention(retention_mode)
    env.configure(_checkpoint_dir_configuration())
