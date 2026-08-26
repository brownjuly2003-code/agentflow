"""Ephemeral staging relay for webhook callbacks addressed to pod loopback."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import signal
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial


@dataclass(frozen=True)
class RelayConfig:
    listen_host: str
    target_host: str
    port_start: int
    port_end: int


def _parse_port(value: str, *, name: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


def load_config(environment: Mapping[str, str] | None = None) -> RelayConfig:
    source = os.environ if environment is None else environment
    target_host = source.get("HOST_LOOPBACK_PROXY_TARGET", "")
    try:
        ipaddress.ip_address(target_host)
    except ValueError as exc:
        raise ValueError("HOST_LOOPBACK_PROXY_TARGET must be an IP address") from exc

    port_start = _parse_port(
        source.get("HOST_LOOPBACK_PROXY_RANGE_START", "32768"),
        name="HOST_LOOPBACK_PROXY_RANGE_START",
    )
    port_end = _parse_port(
        source.get("HOST_LOOPBACK_PROXY_RANGE_END", "65535"),
        name="HOST_LOOPBACK_PROXY_RANGE_END",
    )
    if port_start > port_end:
        raise ValueError("HOST_LOOPBACK_PROXY_RANGE_START must not exceed the range end")

    return RelayConfig(
        listen_host="127.0.0.1",
        target_host=target_host,
        port_start=port_start,
        port_end=port_end,
    )


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _handle(
    config: RelayConfig,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    port = client_writer.get_extra_info("sockname")[1]
    target_reader, target_writer = await asyncio.open_connection(config.target_host, port)
    await asyncio.gather(
        _pipe(client_reader, target_writer),
        _pipe(target_reader, client_writer),
    )


async def run_relay(config: RelayConfig) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    handler = partial(_handle, config)
    servers = [
        await asyncio.start_server(handler, config.listen_host, port)
        for port in range(config.port_start, config.port_end + 1)
    ]
    print(
        f"Host loopback relay listening on {config.listen_host}:"
        f"{config.port_start}-{config.port_end} -> {config.target_host}",
        flush=True,
    )

    await stop.wait()
    for server in servers:
        server.close()
    await asyncio.gather(*(server.wait_closed() for server in servers))


def main() -> int:
    asyncio.run(run_relay(load_config()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
