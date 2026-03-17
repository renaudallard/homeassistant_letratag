"""Config flow for DYMO LetraTag integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import DOMAIN, ble_uuid, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

EXPECTED_SERVICE_UUID = ble_uuid(SERVICE_UUID)


class LetraTagConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DYMO LetraTag."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle bluetooth discovery."""
        _LOGGER.debug(
            "Discovered LetraTag: %s (%s)",
            discovery_info.name,
            discovery_info.address,
        )

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "DYMO LetraTag"
        }

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm bluetooth discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or "DYMO LetraTag",
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: self._discovery_info.name or "DYMO LetraTag",
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or "DYMO LetraTag"
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user-initiated configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=user_input.get(CONF_NAME, "DYMO LetraTag"),
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: user_input.get(CONF_NAME, "DYMO LetraTag"),
                },
            )

        # Try to find already-discovered LetraTag devices
        discovered = async_discovered_service_info(self.hass, connectable=True)
        letratag_devices = {
            info.address: info.name or info.address
            for info in discovered
            if EXPECTED_SERVICE_UUID.lower() in [s.lower() for s in info.service_uuids]
        }

        if letratag_devices:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ADDRESS): vol.In(letratag_devices),
                        vol.Optional(CONF_NAME, default="DYMO LetraTag"): str,
                    }
                ),
                errors=errors,
            )

        # No devices found, allow manual entry
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default="DYMO LetraTag"): str,
                }
            ),
            errors=errors,
        )
