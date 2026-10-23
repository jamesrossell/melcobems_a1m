"""Virtual Setpoint number per unit (reg 17, EEPROM-backed - written on change only)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_TEMP, MIN_TEMP, REG_VSP, TEMP_STEP
from .coordinator import A1MCoordinator
from .entity import A1MUnitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: A1MCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VirtualSetpointNumber(coordinator, s["id"], s["name"])
        for s in coordinator.slaves
    )


class VirtualSetpointNumber(A1MUnitEntity, NumberEntity):
    _attr_name = "Virtual Setpoint"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_TEMP
    _attr_native_max_value = MAX_TEMP
    _attr_native_step = TEMP_STEP
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator: A1MCoordinator, slave: int, name: str) -> None:
        super().__init__(coordinator, slave, name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_vsp"

    @property
    def native_value(self) -> float | None:
        u = self.unit
        return u.virtual_setpoint if u else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(
            self._slave, REG_VSP, int(round(value * 10))
        )
        self.async_write_ha_state()
