# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""DYMO LetraTag integration for Home Assistant.

Provides BLE connectivity to DYMO LetraTag label printers, exposing
printer status as sensors and label printing as services.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bleak.backends.device import BLEDevice
from PIL import Image
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_HAS_CUTTER,
    DOMAIN,
    FONT_MAP,
    LABEL_HEIGHT,
    SERVICE_PRINT_IMAGE,
    SERVICE_PRINT_LABEL,
    normalize_address,
    resolve_font,
)
from .frontend import async_setup_frontend, async_unload_frontend_if_last_entry
from .printer import LetraTagPrinter, PrintError
from .render import render_text, render_text_banner

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# Ways of naming a printer, shared by both services. Services cannot carry a
# device filter on target, so the picker is an ordinary device selector field.
_PRINTER_FIELDS = {
    vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("address"): cv.string,
}

PRINT_LABEL_SCHEMA = vol.Schema(
    {
        **_PRINTER_FIELDS,
        vol.Required("text"): cv.string,
        vol.Optional("copies", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=255)
        ),
        vol.Optional("cut", default=True): cv.boolean,
        vol.Optional("font_size"): vol.All(vol.Coerce(int), vol.Range(min=8, max=64)),
        vol.Optional("font_name"): vol.In(list(FONT_MAP.keys())),
        vol.Optional("font_path"): cv.string,
        vol.Optional("rotate", default=False): cv.boolean,
    }
)

PRINT_IMAGE_SCHEMA = vol.Schema(
    {
        **_PRINTER_FIELDS,
        vol.Required("image_path"): cv.string,
        vol.Optional("copies", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=255)
        ),
        vol.Optional("cut", default=True): cv.boolean,
    }
)


def _entry_ids_for_devices(hass: HomeAssistant, device_ids: list[str]) -> set[str]:
    """Map the devices a call names onto the config entries behind them."""
    registry = dr.async_get(hass)
    entry_ids: set[str] = set()
    for device_id in device_ids:
        device = registry.async_get(device_id)
        if device is None:
            raise HomeAssistantError(f"Unknown device {device_id}")
        entry_ids |= device.config_entries
    return entry_ids


def _get_printer(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[LetraTagPrinter, BLEDevice, bool]:
    """Get the printer a service call is aimed at, its device and cutter flag.

    The printer is picked either from the device selector or by address, for
    automations that would rather carry a string. With one printer
    configured, neither is needed.
    """
    # Config entry ids never start with an underscore, the internal keys do
    entries = {
        key: data
        for key, data in hass.data.get(DOMAIN, {}).items()
        if not key.startswith("_")
    }
    if not entries:
        raise HomeAssistantError("No DYMO LetraTag printer configured")

    chosen: set[str] = set()
    if device_ids := call.data.get(ATTR_DEVICE_ID):
        chosen = _entry_ids_for_devices(hass, device_ids) & set(entries)
        if not chosen:
            raise HomeAssistantError("That device is not a DYMO LetraTag printer")
    elif address := str(call.data.get("address", "")).strip():
        wanted = normalize_address(address)
        chosen = {key for key, data in entries.items() if data["address"] == wanted}
        if not chosen:
            raise HomeAssistantError(f"No DYMO LetraTag printer configured at {wanted}")
    elif len(entries) > 1:
        configured = ", ".join(sorted(data["address"] for data in entries.values()))
        raise HomeAssistantError(
            f"Several printers are configured ({configured}), "
            "pick one with the printer or address option"
        )
    else:
        chosen = set(entries)

    if len(chosen) > 1:
        raise HomeAssistantError("Print on one printer at a time")

    entry_data = entries[chosen.pop()]
    printer: LetraTagPrinter = entry_data["printer"]
    printer_address: str = entry_data["address"]
    entry: ConfigEntry = entry_data["entry"]
    has_cutter = bool(entry.options.get(CONF_HAS_CUTTER, False))

    ble_device = bluetooth.async_ble_device_from_address(
        hass, printer_address, connectable=True
    )
    if ble_device is None:
        raise HomeAssistantError(
            f"Printer {printer_address} is not advertising, "
            "it is out of range or powered off"
        )
    return printer, ble_device, has_cutter


def _migrated_address(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the entry's address, fixing up one stored in the wrong form.

    An address typed in before it was normalized never matched what the
    scanner reports, leaving the entry permanently offline. Put it right in
    place, unless the printer has since been added again properly, in which
    case this entry is a duplicate for the user to remove.
    """
    address: str = entry.data[CONF_ADDRESS]
    normalized = normalize_address(address)
    if normalized == address:
        return address

    taken = {
        other.unique_id
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    }
    if normalized in taken:
        _LOGGER.warning(
            "Config entry for %s is a duplicate of %s and can be removed",
            address,
            normalized,
        )
        return address

    _LOGGER.info("Correcting stored printer address %s to %s", address, normalized)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_ADDRESS: normalized},
        unique_id=normalized,
    )
    return normalized


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DYMO LetraTag from a config entry."""
    address = _migrated_address(hass, entry)
    printer = LetraTagPrinter(address)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "printer": printer,
        "address": address,
        "entry": entry,
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
        printer, ble_device, has_cutter = _get_printer(hass, call)

        text = call.data["text"]
        if not text.strip():
            raise HomeAssistantError("Text cannot be empty")

        # font_name takes priority over font_path
        font_path = call.data.get("font_path")
        font_name = call.data.get("font_name")
        font_size = call.data.get("font_size")
        rotate = call.data.get("rotate", False)

        # Render in executor to avoid blocking the event loop. Finding the
        # font reads the filesystem, so it happens there too.
        def _render() -> Image.Image:
            path = font_path
            if font_name:
                resolved = resolve_font(font_name)
                if resolved is None:
                    _LOGGER.warning(
                        "Font %s is not installed on this host, using the default font",
                        font_name,
                    )
                else:
                    path = resolved
            if path and not Path(path).is_file():
                _LOGGER.warning(
                    "Font file %s cannot be read, using the default font", path
                )
            if rotate:
                return render_text_banner(
                    text,
                    label_height=LABEL_HEIGHT,
                    font_path=path,
                    font_size=font_size,
                )
            return render_text(
                text,
                label_height=LABEL_HEIGHT,
                font_path=path,
                font_size=font_size,
            )

        img = await hass.async_add_executor_job(_render)

        cut = call.data.get("cut", True) if has_cutter else None
        try:
            result = await printer.print_image(
                img=img,
                copies=call.data.get("copies", 1),
                cut=cut,
                ble_device=ble_device,
            )
            _LOGGER.info("Print result: %s", result)
        except PrintError as err:
            raise HomeAssistantError(f"Print failed: {err}") from err

    async def handle_print_image(call: ServiceCall) -> None:
        """Handle the print_image service call."""
        printer, ble_device, has_cutter = _get_printer(hass, call)

        image_path = call.data["image_path"]

        # Restrict to paths under HA config directory
        config_dir = Path(hass.config.path()).resolve()
        try:
            resolved = Path(image_path).resolve()
        except (OSError, ValueError) as err:
            raise HomeAssistantError(f"Invalid image path: {err}") from err
        if not resolved.is_relative_to(config_dir):
            raise HomeAssistantError(f"Image path must be under {config_dir}")

        if not resolved.is_file():
            raise HomeAssistantError(f"Image not found: {image_path}")

        def _load() -> Image.Image:
            with Image.open(str(resolved)) as im:
                im.load()
                return im

        try:
            img = await hass.async_add_executor_job(_load)
        except Exception as err:
            raise HomeAssistantError(f"Cannot open image: {err}") from err

        cut = call.data.get("cut", True) if has_cutter else None
        try:
            result = await printer.print_image(
                img=img,
                copies=call.data.get("copies", 1),
                cut=cut,
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
