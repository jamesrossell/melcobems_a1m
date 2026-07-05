"""Base entity: one Device per indoor unit, availability from the block read."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, UNIT_MODEL
from .coordinator import A1MCoordinator, UnitData


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
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.entry.entry_id}_{self._slave}")},
            via_device=(DOMAIN, self.coordinator.entry.entry_id),
            manufacturer=MANUFACTURER,
            model=UNIT_MODEL,
            name=self._unit_name,
            serial_number=f"M-NET/Modbus address {self._slave}",
            sw_version=u.firmware if u else None,
        )
