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

from .const import (
    DOMAIN,
    FONT_MAP,
    LABEL_HEIGHT,
    SERVICE_PRINT_IMAGE,
    SERVICE_PRINT_LABEL,
    resolve_font,
)
from .frontend import async_setup_frontend, async_unload_frontend_if_last_entry
from .printer import LetraTagPrinter, PrintError
from .render import render_text, render_text_banner

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

PRINT_LABEL_SCHEMA = vol.Schema(
    {
        vol.Required("text"): cv.string,
        vol.Optional("copies", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=255)
        ),
        vol.Optional("cut", default=True): cv.boolean,
        vol.Optional("font_size"): vol.All(vol.Coerce(int), vol.Range(min=6, max=52)),
        vol.Optional("font_name"): vol.In(list(FONT_MAP.keys())),
        vol.Optional("font_path"): cv.string,
        vol.Optional("rotate", default=False): cv.boolean,
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
    domain_data = hass.data.get(DOMAIN, {})

    # Find first config entry key (skip internal keys starting with _)
    entry_id = next(
        (k for k in domain_data if not k.startswith("_")),
        None,
    )
    if entry_id is None:
        raise HomeAssistantError("No DYMO LetraTag printer configured")

    entry_data = domain_data[entry_id]
    printer: LetraTagPrinter = entry_data["printer"]
    address: str = entry_data["address"]

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

    # Register frontend card securely via StaticPathConfig + Lovelace resource
    await async_setup_frontend(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Check if any config entries remain (skip internal keys)
    remaining = [k for k in hass.data.get(DOMAIN, {}) if not k.startswith("_")]
    if not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_PRINT_LABEL)
        hass.services.async_remove(DOMAIN, SERVICE_PRINT_IMAGE)
        await async_unload_frontend_if_last_entry(hass)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_print_label(call: ServiceCall) -> None:
        """Handle the print_label service call."""
        printer, ble_device = _get_printer(hass)

        text = call.data["text"]
        if not text.strip():
            raise HomeAssistantError("Text cannot be empty")

        # Resolve font: font_name takes priority over font_path
        font_path = call.data.get("font_path")
        font_name = call.data.get("font_name")
        if font_name:
            resolved = resolve_font(font_name)
            if resolved:
                font_path = resolved

        font_size = call.data.get("font_size")
        rotate = call.data.get("rotate", False)

        # Render in executor to avoid blocking the event loop
        def _render() -> Image.Image:
            if rotate:
                return render_text_banner(
                    text,
                    label_height=LABEL_HEIGHT,
                    font_path=font_path,
                    font_size=font_size,
                )
            return render_text(
                text,
                label_height=LABEL_HEIGHT,
                font_path=font_path,
                font_size=font_size,
            )

        img = await hass.async_add_executor_job(_render)

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

    async def handle_print_image(call: ServiceCall) -> None:
        """Handle the print_image service call."""
        printer, ble_device = _get_printer(hass)

        image_path = call.data["image_path"]

        # Restrict to paths under HA config directory
        config_dir = Path(hass.config.path())
        try:
            resolved = Path(image_path).resolve()
            if not str(resolved).startswith(str(config_dir.resolve())):
                raise HomeAssistantError(f"Image path must be under {config_dir}")
        except (OSError, ValueError) as err:
            raise HomeAssistantError(f"Invalid image path: {err}") from err

        if not resolved.is_file():
            raise HomeAssistantError(f"Image not found: {image_path}")

        def _load() -> Image.Image:
            return Image.open(str(resolved))

        try:
            img = await hass.async_add_executor_job(_load)
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
