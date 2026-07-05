"""Climate entity per indoor unit.

Semantics:
- current temperature: the external room sensor when Setpoint Offset is active
  (the A1M's reg-16 echo, which is authoritative for what the unit thermostats
  on), else the unit's own return-air reading (reg 8).
- target temperature: the Virtual Setpoint (reg 17) when offset is active
  (EEPROM-safe, written on change only), else the raw unit setpoint (reg 1).
- No AUTO mode: on a 2-pipe PUMY the unit demotes Auto to FAN (verified live).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FAN_TO_HA,
    HA_TO_FAN,
    HVAC_TO_MODE,
    MAX_TEMP,
    MIN_TEMP,
    MODE_TO_HVAC,
    REG_FAN,
    REG_MODE,
    REG_POWER,
    REG_SETPOINT,
    REG_VSP,
    TEMP_STEP,
)
from .coordinator import A1MCoordinator
from .entity import A1MUnitEntity

HVAC_MODES = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY]
HVAC_STR_TO_MODE = {
    "heat": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "cool": HVACMode.COOL,
    "fan_only": HVACMode.FAN_ONLY,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: A1MCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        A1MClimate(coordinator, s["id"], s["name"]) for s in coordinator.slaves
    )


class A1MClimate(A1MUnitEntity, ClimateEntity):
    """The main control surface for one indoor unit."""

    _attr_name = None  # primary entity: takes the device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = HVAC_MODES
    _attr_fan_modes = list(HA_TO_FAN)
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: A1MCoordinator, slave: int, unit_name: str) -> None:
        super().__init__(coordinator, slave, unit_name)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{slave}_climate"

    # ------------------------------------------------------------------ helpers
    def _offset_active(self) -> bool:
        u = self.unit
        return (
            u is not None
            and self.coordinator._feed_config(self._slave) is not None
            and u.bms_room_echo > 0
        )

    # ------------------------------------------------------------------ state
    @property
    def hvac_mode(self) -> HVACMode | None:
        u = self.unit
        if u is None:
            return None
        if not u.power_on:
            return HVACMode.OFF
        return HVAC_STR_TO_MODE.get(MODE_TO_HVAC.get(u.mode_raw, ""), HVACMode.FAN_ONLY)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Best-effort action (the ATA map exposes no thermo-on register)."""
        u = self.unit
        if u is None:
            return None
        if not u.power_on:
            return HVACAction.OFF
        mode = MODE_TO_HVAC.get(u.mode_raw, "")
        cur = self.current_temperature
        tgt = self.target_temperature
        if mode == "fan_only":
            return HVACAction.FAN
        if mode == "dry":
            return HVACAction.DRYING
        if cur is None or tgt is None:
            return HVACAction.IDLE
        if mode == "cool":
            return HVACAction.COOLING if cur > tgt + 0.3 else HVACAction.IDLE
        if mode == "heat":
            return HVACAction.HEATING if cur < tgt - 0.3 else HVACAction.IDLE
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        u = self.unit
        if u is None:
            return None
        if self._offset_active():
            return u.bms_room_echo / 10.0
        return u.return_air

    @property
    def target_temperature(self) -> float | None:
        u = self.unit
        if u is None:
            return None
        return u.virtual_setpoint if self._offset_active() else u.setpoint

    @property
    def fan_mode(self) -> str | None:
        u = self.unit
        if u is None:
            return None
        return FAN_TO_HA.get(u.regs[REG_FAN])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        u = self.unit
        if u is None:
            return {}
        return {
            "setpoint_offset_active": self._offset_active(),
            "unit_setpoint_reg1": u.setpoint,
            "return_air_reg8": u.return_air,
        }

    # ------------------------------------------------------------------ commands
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_write(self._slave, REG_POWER, 0)
            return
        u = self.unit
        if u is not None and not u.power_on:
            await self.coordinator.bridge.write_register(self._slave, REG_POWER, 1)
        await self.coordinator.async_write(
            self._slave, REG_MODE, HVAC_TO_MODE[hvac_mode.value]
        )

    async def async_turn_on(self) -> None:
        await self.coordinator.async_write(self._slave, REG_POWER, 1)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_write(self._slave, REG_POWER, 0)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        value = int(round(float(temp) * 10))
        reg = REG_VSP if self._offset_active() else REG_SETPOINT
        await self.coordinator.async_write(self._slave, reg, value)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode in HA_TO_FAN:
            await self.coordinator.async_write(self._slave, REG_FAN, HA_TO_FAN[fan_mode])
