"""Problem flag per unit (fault code != 8000)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import A1MCoordinator
from .entity import A1MUnitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: A1MCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ProblemSensor(coordinator, s["id"], s["name"]) for s in coordinator.slaves
    )


class ProblemSensor(A1MUnitEntity, BinarySensorEntity):
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: A1MCoordinator, slave: int, name: str) -> None:
        super().__init__(coordinator, slave, name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_problem"

    @property
    def is_on(self) -> bool | None:
        u = self.unit
        return (not u.fault_ok) if u else None
