"""DYMO LetraTag integration for Home Assistant.

Provides BLE connectivity to DYMO LetraTag label printers, exposing
printer status as sensors and label printing as services.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, SERVICE_PRINT_IMAGE, SERVICE_PRINT_LABEL
from .printer import LetraTagPrinter, PrintError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

PRINT_LABEL_SCHEMA = vol.Schema(
    {
        vol.Required("text"): cv.string,
        vol.Optional("copies", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=255)
        ),
        vol.Optional("cut", default=True): cv.boolean,
        vol.Optional("font_size"): vol.All(vol.Coerce(int), vol.Range(min=6, max=26)),
        vol.Optional("font_path"): cv.string,
    }
)

PRINT_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("image_path"): cv.string,
        vol.Optional("copies", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=255)
        ),
        vol.Optional("cut", default=True): cv.boolean,
    }
)


def _get_printer(hass: HomeAssistant) -> tuple[LetraTagPrinter, object | None]:
    """Get the first configured printer and its BLE device."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No DYMO LetraTag printer configured")

    entry_id = next(iter(entries))
    printer: LetraTagPrinter = entries[entry_id]["printer"]
    address = entries[entry_id]["address"]

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    return printer, ble_device


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DYMO LetraTag from a config entry."""
    address = entry.data[CONF_ADDRESS]
    printer = LetraTagPrinter(address)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "printer": printer,
        "address": address,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once, shared across all entries)
    if not hass.services.has_service(DOMAIN, SERVICE_PRINT_LABEL):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Unregister services if no entries remain
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_PRINT_LABEL)
        hass.services.async_remove(DOMAIN, SERVICE_PRINT_IMAGE)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_print_label(call: ServiceCall) -> None:
        """Handle the print_label service call."""
        printer, ble_device = _get_printer(hass)

        try:
            result = await printer.print_label(
                text=call.data["text"],
                copies=call.data.get("copies", 1),
                cut=call.data.get("cut", True),
                font_path=call.data.get("font_path"),
                font_size=call.data.get("font_size"),
                ble_device=ble_device,
            )
            _LOGGER.info("Print result: %s", result)
        except PrintError as err:
            raise HomeAssistantError(f"Print failed: {err}") from err

    async def handle_print_image(call: ServiceCall) -> None:
        """Handle the print_image service call."""
        printer, ble_device = _get_printer(hass)

        image_path = call.data["image_path"]
        if not Path(image_path).is_file():
            raise HomeAssistantError(f"Image not found: {image_path}")

        try:
            img = Image.open(image_path)
        except Exception as err:
            raise HomeAssistantError(f"Cannot open image: {err}") from err

        try:
            result = await printer.print_image(
                img=img,
                copies=call.data.get("copies", 1),
                cut=call.data.get("cut", True),
                ble_device=ble_device,
            )
            _LOGGER.info("Print result: %s", result)
        except PrintError as err:
            raise HomeAssistantError(f"Print failed: {err}") from err

    hass.services.async_register(
        DOMAIN, SERVICE_PRINT_LABEL, handle_print_label, PRINT_LABEL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PRINT_IMAGE, handle_print_image, PRINT_IMAGE_SCHEMA
    )
