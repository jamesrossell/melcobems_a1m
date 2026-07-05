"""Modbus transport bridge for the A1M bus.

Wraps pymodbus (whichever version Home Assistant ships) behind a tiny API:
    read_block(slave) -> list[int] | None
    write_register(slave, address, value) -> bool
Serialises all bus access behind one asyncio lock and inserts a short
inter-frame gap, matching the A1M's RS-485 timing expectations.
"""
from __future__ import annotations

import asyncio
import inspect
import logging

from .const import BLOCK_COUNT, BLOCK_START

_LOGGER = logging.getLogger(__name__)

INTER_FRAME_GAP = 0.03  # seconds between transactions on the shared bus


class A1MBridge:
    """One instance per config entry / physical bus."""

    def __init__(
        self,
        connection: str,
        *,
        serial_port: str | None = None,
        baudrate: int = 9600,
        tcp_host: str | None = None,
        tcp_port: int = 502,
    ) -> None:
        self._connection = connection
        self._serial_port = serial_port
        self._baudrate = baudrate
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port
        self._client = None
        self._lock = asyncio.Lock()
        self._slave_kwarg: str | None = None  # pymodbus API drift: slave= vs device_id=

    async def connect(self) -> None:
        if self._connection == "serial":
            from pymodbus.client import AsyncModbusSerialClient

            self._client = AsyncModbusSerialClient(
                port=self._serial_port,
                baudrate=self._baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=2,
            )
        else:
            from pymodbus.client import AsyncModbusTcpClient

            self._client = AsyncModbusTcpClient(
                host=self._tcp_host, port=self._tcp_port, timeout=2
            )
        connected = await self._client.connect()
        if not connected:
            raise ConnectionError(
                f"Could not open {self._serial_port or self._tcp_host}"
            )
        # Detect the slave-id keyword once (pymodbus 3.x: slave=, 4.x: device_id=)
        sig = inspect.signature(self._client.read_holding_registers)
        params = sig.parameters
        if "slave" in params:
            self._slave_kwarg = "slave"
        elif "device_id" in params:
            self._slave_kwarg = "device_id"
        elif "unit" in params:
            self._slave_kwarg = "unit"
        else:
            self._slave_kwarg = "slave"  # last resort
        _LOGGER.debug("A1M bridge connected; slave kwarg = %s", self._slave_kwarg)

    async def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001 - best effort on teardown
                pass
            self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None and getattr(self._client, "connected", False)

    def _kw(self, slave: int) -> dict:
        return {self._slave_kwarg: slave}

    async def read_block(self, slave: int) -> list[int] | None:
        """One FC03 read of holding registers 0..19. None on failure."""
        if self._client is None:
            return None
        async with self._lock:
            try:
                rr = await self._client.read_holding_registers(
                    BLOCK_START, count=BLOCK_COUNT, **self._kw(slave)
                )
            except Exception as exc:  # noqa: BLE001 - transport errors -> offline
                _LOGGER.debug("slave %s read failed: %s", slave, exc)
                return None
            finally:
                await asyncio.sleep(INTER_FRAME_GAP)
        if rr is None or rr.isError() or not getattr(rr, "registers", None):
            return None
        regs = list(rr.registers)
        return regs if len(regs) >= BLOCK_COUNT else None

    async def write_register(self, slave: int, address: int, value: int) -> bool:
        """One FC06 single-register write."""
        if self._client is None:
            return False
        async with self._lock:
            try:
                wr = await self._client.write_register(
                    address, value, **self._kw(slave)
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "slave %s write reg %s=%s failed: %s", slave, address, value, exc
                )
                return False
            finally:
                await asyncio.sleep(INTER_FRAME_GAP)
        return wr is not None and not wr.isError()
