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
                conn = user_input[CONF_CONNECTION]
                bridge = A1MBridge(
                    conn,
                    serial_port=user_input.get(CONF_SERIAL_PORT),
                    baudrate=user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                    tcp_host=user_input.get(CONF_TCP_HOST),
                    tcp_port=user_input.get(CONF_TCP_PORT, 502),
                )
                try:
                    await bridge.connect()
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"
                else:
                    bad: list[str] = []
                    for s in slaves:
                        regs = await bridge.read_block(s["id"])
                        if regs is None:
                            bad.append(f"{s['id']} (no reply)")
                        elif regs[REG_SYSTYPE] != 0:
                            bad.append(f"{s['id']} (not Air-To-Air)")
                        else:
                            _LOGGER.info(
                                "A1M slave %s validated, fw raw %s",
                                s["id"],
                                regs[REG_FW],
                            )
                    await bridge.close()
                    if bad:
                        errors["base"] = "slave_failed"
                        self._bad = ", ".join(bad)
                if not errors:
                    unique = (
                        user_input.get(CONF_SERIAL_PORT)
                        or f"{user_input.get(CONF_TCP_HOST)}:{user_input.get(CONF_TCP_PORT)}"
                    )
                    await self.async_set_unique_id(unique)
                    self._abort_if_unique_id_configured()
                    data = {
                        CONF_CONNECTION: conn,
                        CONF_SERIAL_PORT: user_input.get(CONF_SERIAL_PORT),
                        CONF_BAUDRATE: user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                        CONF_TCP_HOST: user_input.get(CONF_TCP_HOST),
                        CONF_TCP_PORT: user_input.get(CONF_TCP_PORT, 502),
                        CONF_SLAVES: slaves,
                    }
                    return self.async_create_entry(
                        title=user_input.get("title") or "Mitsubishi VRF (A1M)",
                        data=data,
                    )

        schema = vol.Schema(
            {
                vol.Optional("title", default="Mitsubishi VRF (A1M)"): str,
                vol.Required(CONF_CONNECTION, default=CONN_SERIAL): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[CONN_SERIAL, CONN_TCP],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_SERIAL_PORT, default=DEFAULT_PORT_HINT): str,
                vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): int,
                vol.Optional(CONF_TCP_HOST): str,
                vol.Optional(CONF_TCP_PORT, default=502): int,
                vol.Required("slaves_raw", default=DEFAULT_SLAVES): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

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
