"""Config + options flow for the A1M bus."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .bridge import A1MBridge
from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION,
    CONF_SERIAL_PORT,
    CONF_SLAVES,
    CONF_TCP_HOST,
    CONF_TCP_PORT,
    CONN_SERIAL,
    CONN_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPT_EXT_ENTITY,
    OPT_OFFSET_ENABLED,
    OPT_SCAN_INTERVAL,
    REG_FW,
    REG_SYSTYPE,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT_HINT = "/dev/serial/by-id/..."
DEFAULT_SLAVES = "1:Unit 1, 2:Unit 2"


def _parse_slaves(raw: str) -> list[dict]:
    """Parse '1:Kitchen 1, 2:Kitchen 2' (name optional) into slave dicts."""
    out: list[dict] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            sid, name = part.split(":", 1)
        else:
            sid, name = part, f"Unit {part}"
        out.append({"id": int(sid.strip()), "name": name.strip()})
    if not out:
        raise ValueError("no slaves")
    ids = [s["id"] for s in out]
    if len(ids) != len(set(ids)) or any(not 1 <= i <= 247 for i in ids):
        raise ValueError("bad slave ids")
    return out


def _transport_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Connection fields shared by the user and reconfigure steps."""
    host_kwargs = {"default": defaults[CONF_TCP_HOST]} if defaults.get(CONF_TCP_HOST) else {}
    return {
        vol.Required(
            CONF_CONNECTION, default=defaults.get(CONF_CONNECTION, CONN_SERIAL)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[CONN_SERIAL, CONN_TCP],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(
            CONF_SERIAL_PORT, default=defaults.get(CONF_SERIAL_PORT) or DEFAULT_PORT_HINT
        ): str,
        vol.Optional(
            CONF_BAUDRATE, default=defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
        ): int,
        vol.Optional(CONF_TCP_HOST, **host_kwargs): str,
        vol.Optional(CONF_TCP_PORT, default=defaults.get(CONF_TCP_PORT, 502)): int,
    }


def _transport_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise the connection fields; the unused transport's fields are cleared."""
    conn = user_input[CONF_CONNECTION]
    return {
        CONF_CONNECTION: conn,
        CONF_SERIAL_PORT: user_input.get(CONF_SERIAL_PORT) if conn == CONN_SERIAL else None,
        CONF_BAUDRATE: user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
        CONF_TCP_HOST: user_input.get(CONF_TCP_HOST) if conn == CONN_TCP else None,
        CONF_TCP_PORT: user_input.get(CONF_TCP_PORT, 502),
    }


def _bus_unique_id(transport: dict[str, Any]) -> str:
    return transport[CONF_SERIAL_PORT] or f"{transport[CONF_TCP_HOST]}:{transport[CONF_TCP_PORT]}"


async def _probe(transport: dict[str, Any], slaves: list[dict]) -> tuple[str | None, str]:
    """Open the transport and check every unit answers as Air-To-Air.

    Returns (error_key or None, description of failed units).
    """
    bridge = A1MBridge(
        transport[CONF_CONNECTION],
        serial_port=transport[CONF_SERIAL_PORT],
        baudrate=transport[CONF_BAUDRATE],
        tcp_host=transport[CONF_TCP_HOST],
        tcp_port=transport[CONF_TCP_PORT],
    )
    try:
        await bridge.connect()
    except Exception:  # noqa: BLE001
        return "cannot_connect", ""
    bad: list[str] = []
    try:
        for s in slaves:
            regs = await bridge.read_block(s["id"])
            if regs is None:
                bad.append(f"{s['id']} (no reply)")
            elif regs[REG_SYSTYPE] != 0:
                bad.append(f"{s['id']} (not Air-To-Air)")
            else:
                _LOGGER.info("A1M slave %s validated, fw raw %s", s["id"], regs[REG_FW])
    finally:
        await bridge.close()
    return ("slave_failed" if bad else None), ", ".join(bad)


class A1MConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one bus: transport + the units on it (validated live)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                slaves = _parse_slaves(user_input["slaves_raw"])
            except (ValueError, TypeError):
                errors["slaves_raw"] = "invalid_slaves"
                slaves = []
            if not errors:
                transport = _transport_data(user_input)
                err, self._bad = await _probe(transport, slaves)
                if err:
                    errors["base"] = err
                else:
                    await self.async_set_unique_id(_bus_unique_id(transport))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user_input.get("title") or "Mitsubishi VRF (A1M)",
                        data={**transport, CONF_SLAVES: slaves},
                    )

        schema = vol.Schema(
            {
                vol.Optional("title", default="Mitsubishi VRF (A1M)"): str,
                **_transport_schema({}),
                vol.Required("slaves_raw", default=DEFAULT_SLAVES): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move an existing bus to a new transport (e.g. USB serial -> PoE
        Modbus TCP gateway) while keeping the entry, its entities and history.

        The running entry is unloaded first so a serial port it holds is free
        for the probe; if the probe fails the entry is set back up unchanged.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders = {"bad": ""}
        if user_input is not None:
            transport = _transport_data(user_input)
            if transport[CONF_CONNECTION] == CONN_TCP and not transport[CONF_TCP_HOST]:
                errors[CONF_TCP_HOST] = "host_required"
            else:
                await self.hass.config_entries.async_unload(entry.entry_id)
                err, placeholders["bad"] = await _probe(transport, list(entry.data[CONF_SLAVES]))
                if err:
                    errors["base"] = err
                    await self.hass.config_entries.async_setup(entry.entry_id)
                else:
                    unique = _bus_unique_id(transport)
                    for other in self._async_current_entries(include_ignore=False):
                        if other.entry_id != entry.entry_id and other.unique_id == unique:
                            await self.hass.config_entries.async_setup(entry.entry_id)
                            return self.async_abort(reason="already_configured")
                    return self.async_update_reload_and_abort(
                        entry, unique_id=unique, data_updates=transport
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(_transport_schema(dict(entry.data))),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> A1MOptionsFlow:
        return A1MOptionsFlow()


class A1MOptionsFlow(OptionsFlow):
    """Scan interval + per-unit external room sensor for the Setpoint Offset."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            cleaned = {
                k: v
                for k, v in user_input.items()
                if not (k.startswith("ext_entity_") and v in ("", None))
            }
            return self.async_create_entry(title="", data=cleaned)

        opts = self.config_entry.options
        slaves = self.config_entry.data[CONF_SLAVES]
        fields: dict[Any, Any] = {
            vol.Optional(
                OPT_SCAN_INTERVAL,
                default=opts.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(int, vol.Range(min=10, max=300))
        }
        for s in slaves:
            ek = OPT_EXT_ENTITY.format(slave=s["id"])
            ok = OPT_OFFSET_ENABLED.format(slave=s["id"])
            kwargs = {"default": opts[ek]} if opts.get(ek) else {}
            fields[vol.Optional(ek, **kwargs)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            )
            fields[vol.Optional(ok, default=opts.get(ok, False))] = bool
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
