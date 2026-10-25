"""MelcoBEMS MINI (A1M) — Mitsubishi VRF over Modbus, one Device per indoor unit."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .bridge import A1MBridge
from .const import (
    BUS_MODEL,
    CONF_BAUDRATE,
    CONF_CONNECTION,
    CONF_SERIAL_PORT,
    CONF_SLAVES,
    CONF_TCP_HOST,
    CONF_TCP_PORT,
    CONN_SERIAL,
    DEFAULT_BAUDRATE,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import A1MCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    bridge = A1MBridge(
        data.get(CONF_CONNECTION, CONN_SERIAL),
        serial_port=data.get(CONF_SERIAL_PORT),
        baudrate=data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
        tcp_host=data.get(CONF_TCP_HOST),
        tcp_port=data.get(CONF_TCP_PORT, 502),
    )
    try:
        await bridge.connect()
    except ConnectionError as exc:
        from homeassistant.exceptions import ConfigEntryNotReady

        raise ConfigEntryNotReady(str(exc)) from exc

    coordinator = A1MCoordinator(hass, entry, bridge, list(data[CONF_SLAVES]))
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Bus device; unit devices hang off it (via_device_id, see entity.py).
    dev_reg = dr.async_get(hass)
    coordinator.bus_device_id = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=BUS_MODEL,
        name=entry.title,
    ).id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Safety: on HA stop, disable the Setpoint Offset on every fed unit so the
    # A1M never free-runs on a frozen room temperature.
    async def _on_stop(_event) -> None:
        await coordinator.async_disarm_all()
        await bridge.close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed -> reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: A1MCoordinator = hass.data[DOMAIN][entry.entry_id]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_disarm_all()
        await coordinator.bridge.close()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
