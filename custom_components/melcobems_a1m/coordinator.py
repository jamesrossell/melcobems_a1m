"""Data coordinator + Setpoint Offset engine for the A1M bus."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .bridge import A1MBridge
from .const import (
    BMS_MAX,
    BMS_MIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXT_STALE_SECONDS,
    OPT_EXT_ENTITY,
    OPT_OFFSET_ENABLED,
    OPT_SCAN_INTERVAL,
    REG_BMS_ROOM,
    REG_FAULT,
    REG_FW,
    REG_MODE,
    REG_POWER,
    REG_RETURN_AIR,
    REG_SETPOINT,
    REG_VSP,
    FAULT_OK,
)

_LOGGER = logging.getLogger(__name__)

# The A1M reports a written value back only on a later poll (~30 s observed),
# so a just-written register is held in the cache until the readback agrees or
# this hold expires; otherwise an early poll would flip the UI back and forth.
PENDING_HOLD = 60  # seconds


@dataclass
class UnitData:
    """Decoded snapshot of one indoor unit."""

    slave: int
    regs: list[int]

    @property
    def power_on(self) -> bool:
        return self.regs[REG_POWER] == 1

    @property
    def mode_raw(self) -> int:
        return self.regs[REG_MODE]

    @property
    def setpoint(self) -> float:
        return self.regs[REG_SETPOINT] / 10.0

    @property
    def return_air(self) -> float:
        raw = self.regs[REG_RETURN_AIR]
        if raw >= 0x8000:  # int16 two's complement
            raw -= 0x10000
        return raw / 10.0

    @property
    def firmware(self) -> str:
        raw = self.regs[REG_FW]
        return f"{raw // 10000}.{(raw // 100) % 100}.{raw % 100}" if raw else "?"

    @property
    def fault(self) -> int:
        return self.regs[REG_FAULT]

    @property
    def fault_ok(self) -> bool:
        return self.fault == FAULT_OK

    @property
    def bms_room_echo(self) -> int:
        return self.regs[REG_BMS_ROOM]

    @property
    def virtual_setpoint(self) -> float:
        return self.regs[REG_VSP] / 10.0


class A1MCoordinator(DataUpdateCoordinator[dict[int, UnitData]]):
    """Polls every unit with one block read per cycle, then runs the offset feed."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        bridge: A1MBridge,
        slaves: list[dict],
    ) -> None:
        interval = entry.options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}:{entry.title}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.entry = entry
        self.bridge = bridge
        self.slaves = slaves  # [{"id": 1, "name": "Kitchen 1"}, ...]
        self.bus_device_id: str | None = None  # registry id of the bus device, set in setup
        self._armed: set[int] = set()  # slaves we last fed a non-zero room temp
        # (slave, register) -> (written value, monotonic expiry); see PENDING_HOLD
        self._pending: dict[tuple[int, int], tuple[int, float]] = {}

    # ------------------------------------------------------------------ polling
    async def _async_update_data(self) -> dict[int, UnitData]:
        data: dict[int, UnitData] = {}
        for s in self.slaves:
            slave = s["id"]
            regs = await self.bridge.read_block(slave)
            if regs is not None:
                self._apply_pending(slave, regs)
                data[slave] = UnitData(slave=slave, regs=regs)
        if not data:
            raise UpdateFailed("No A1M answered on the bus")
        await self._run_offset_feed(data)
        return data

    # -------------------------------------------------------- setpoint offset feed
    def _feed_config(self, slave: int) -> str | None:
        """Return the external temp entity for a slave, if offset is enabled."""
        opts = self.entry.options
        if not opts.get(OPT_OFFSET_ENABLED.format(slave=slave)):
            return None
        return opts.get(OPT_EXT_ENTITY.format(slave=slave)) or None

    async def _run_offset_feed(self, data: dict[int, UnitData]) -> None:
        """Write real room temps to REG_BMS_ROOM; 0 when stale/disabled.

        Compares against the register echo from this cycle's block read, so we
        only write on change — and automatically re-arm if the A1M reset to 0
        (power loss / its 2-minute CN105 failsafe).
        """
        for s in self.slaves:
            slave = s["id"]
            if slave not in data:
                continue
            entity_id = self._feed_config(slave)
            echo = data[slave].bms_room_echo
            if entity_id is None:
                # feature not configured: if we armed it earlier, disarm once
                if slave in self._armed:
                    if await self.bridge.write_register(slave, REG_BMS_ROOM, 0):
                        self._armed.discard(slave)
                continue
            target = 0
            st = self.hass.states.get(entity_id)
            if st is not None and st.state not in ("unknown", "unavailable", "none"):
                age = (dt_util.utcnow() - st.last_updated).total_seconds()
                if age < EXT_STALE_SECONDS:
                    try:
                        target = int(round(float(st.state) * 10))
                        target = max(BMS_MIN, min(BMS_MAX, target))
                    except (ValueError, TypeError):
                        target = 0
            if target != echo:
                if await self.bridge.write_register(slave, REG_BMS_ROOM, target):
                    _LOGGER.debug("offset feed slave %s: %s -> %s", slave, echo, target)
            if target > 0:
                self._armed.add(slave)
            else:
                self._armed.discard(slave)

    async def async_disarm_all(self) -> None:
        """Write 0 to every configured unit's BMS room register (shutdown path)."""
        for s in self.slaves:
            slave = s["id"]
            if self._feed_config(slave) is not None or slave in self._armed:
                await self.bridge.write_register(slave, REG_BMS_ROOM, 0)
        self._armed.clear()

    # ---------------------------------------------------------------- write API
    def _apply_pending(self, slave: int, regs: list[int]) -> None:
        """Overlay just-written values on a fresh read until the A1M echoes them."""
        now = time.monotonic()
        for (s, address), (value, expiry) in list(self._pending.items()):
            if s != slave:
                continue
            if regs[address] == value or now > expiry:
                del self._pending[(s, address)]
            else:
                regs[address] = value

    async def async_write(self, slave: int, address: int, value: int) -> bool:
        """Write a register and update the cached snapshot optimistically.

        The calling entity then writes its state straight away, inside the
        service call - so the change carries the caller's context (the user
        or automation that asked) instead of an anonymous poll 30 s later.
        """
        ok = await self.bridge.write_register(slave, address, value)
        if not ok:
            _LOGGER.warning("write failed: slave %s reg %s = %s", slave, address, value)
            return False
        self._pending[(slave, address)] = (value, time.monotonic() + PENDING_HOLD)
        unit = (self.data or {}).get(slave)
        if unit is not None:
            unit.regs[address] = value
        return True
