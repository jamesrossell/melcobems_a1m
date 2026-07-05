"""Per-unit sensors: return air, fault, firmware + comms diagnostics."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FAULT_CN105, FAULT_OK, REG_COMMS
from .coordinator import A1MCoordinator
from .entity import A1MUnitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: A1MCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for s in coordinator.slaves:
        slave, name = s["id"], s["name"]
        entities.append(ReturnAirSensor(coordinator, slave, name))
        entities.append(FaultSensor(coordinator, slave, name))
        entities.append(FirmwareSensor(coordinator, slave, name))
        entities.append(CommsCounterSensor(coordinator, slave, name))
    async_add_entities(entities)


class ReturnAirSensor(A1MUnitEntity, SensorEntity):
    """TH21 return-air temperature at the unit inlet (reg 8)."""

    _attr_name = "Return Air Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: A1MCoordinator, slave: int, name: str) -> None:
        super().__init__(coordinator, slave, name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_return_air"

    @property
    def native_value(self) -> float | None:
        u = self.unit
        return u.return_air if u else None


class FaultSensor(A1MUnitEntity, SensorEntity):
    """Human-readable fault state from reg 12."""

    _attr_name = "Fault"
    _attr_icon = "mdi:alert-circle-check"

    def __init__(self, coordinator: A1MCoordinator, slave: int, name: str) -> None:
        super().__init__(coordinator, slave, name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_fault"

    @property
    def native_value(self) -> str | None:
        u = self.unit
        if u is None:
            return None
        if u.fault == FAULT_OK:
            return "OK"
        if u.fault == FAULT_CN105:
            return "A1M-to-unit comms fault (CN105)"
        return f"Unit fault {u.fault}"

    @property
    def extra_state_attributes(self) -> dict:
        u = self.unit
        return {"raw_code": u.fault} if u else {}


class FirmwareSensor(A1MUnitEntity, SensorEntity):
    """A1M firmware version (reg 10)."""

    _attr_name = "A1M Firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: A1MCoordinator, slave: int, name: str) -> None:
        super().__init__(coordinator, slave, name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_fw"

    @property
    def native_value(self) -> str | None:
        u = self.unit
        return u.firmware if u else None


class CommsCounterSensor(A1MUnitEntity, SensorEntity):
    """Bus-health canary: A1M Modbus transaction counter (reg 11, wraps at 65535)."""

    _attr_name = "Modbus Comms Counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: A1MCoordinator, slave: int, name: str) -> None:
        super().__init__(coordinator, slave, name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_comms"

    @property
    def native_value(self) -> int | None:
        u = self.unit
        return u.regs[REG_COMMS] if u else None
