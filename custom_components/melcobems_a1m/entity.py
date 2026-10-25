"""Base entity: one Device per indoor unit, availability from the block read."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, UNIT_MODEL
from .coordinator import A1MCoordinator, UnitData

# HA 2026.8 replaced DeviceInfo's via_device (identifier pair) with via_device_id
# (registry id); the old key warns now and stops working in 2027.8. Keep the old
# key only for HA versions that predate via_device_id.
_HAS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


class A1MUnitEntity(CoordinatorEntity[A1MCoordinator]):
    """Common plumbing for all per-unit entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: A1MCoordinator, slave: int, unit_name: str) -> None:
        super().__init__(coordinator)
        self._slave = slave
        self._unit_name = unit_name

    @property
    def unit(self) -> UnitData | None:
        return (self.coordinator.data or {}).get(self._slave)

    @property
    def available(self) -> bool:
        return super().available and self.unit is not None

    @property
    def device_info(self) -> DeviceInfo:
        u = self.unit
        info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.entry.entry_id}_{self._slave}")},
            manufacturer=MANUFACTURER,
            model=UNIT_MODEL,
            name=self._unit_name,
            serial_number=f"M-NET/Modbus address {self._slave}",
            sw_version=u.firmware if u else None,
        )
        if _HAS_VIA_DEVICE_ID:
            info["via_device_id"] = self.coordinator.bus_device_id
        else:
            info["via_device"] = (DOMAIN, self.coordinator.entry.entry_id)
        return info
