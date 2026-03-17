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

"""Sensor platform for DYMO LetraTag integration.

The LetraTag does not include manufacturer data in its BLE
advertisements. Instead, we watch for advertisements to detect
when the printer is on, then connect via GATT to read status.
"""

from __future__ import annotations

import logging
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONNECT_TIMEOUT,
    DOMAIN,
    PRINT_REPLY_UUID,
    PRINT_REQUEST_UUID,
    ble_uuid,
)
from .protocol import parse_status_info

_LOGGER = logging.getLogger(__name__)

_BATTERY_MAP = {0: 10, 1: 40, 2: 70, 3: 100}
_STATUS_CMD = bytes([0x1B, 0x41, 0x00])


async def _read_printer_status(hass: HomeAssistant, address: str) -> dict[str, Any]:
    """Connect to the printer and read all available data via GATT.

    Enumerates all readable characteristics to discover battery,
    device info, and cassette data. Also sends the ESC-A status
    command for the short status reply.
    """
    write_uuid = ble_uuid(PRINT_REQUEST_UUID)
    reply_uuid = ble_uuid(PRINT_REPLY_UUID)

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is None:
        return {}

    result: dict[str, Any] = {}

    try:
        async with BleakClient(ble_device, timeout=CONNECT_TIMEOUT) as client:
            # Read all readable characteristics
            for service in client.services:
                for char in service.characteristics:
                    if "read" not in char.properties:
                        continue
                    try:
                        data = await client.read_gatt_char(char.uuid)
                        _LOGGER.debug(
                            "GATT %s/%s: %s",
                            service.uuid,
                            char.uuid,
                            data.hex() if data else "empty",
                        )
                        # Device Information Service chars
                        _text_chars = {
                            "00002a29": "manufacturer",
                            "00002a24": "model",
                            "00002a25": "serial",
                            "00002a26": "firmware",
                            "00002a27": "hardware_revision",
                        }
                        for uuid_frag, key in _text_chars.items():
                            if uuid_frag in char.uuid:
                                result[key] = data.decode(
                                    "utf-8", errors="replace"
                                ).strip()
                                break
                    except Exception as err:
                        _LOGGER.debug("Cannot read %s: %s", char.uuid, err)

            # Send status request and read reply
            try:
                await client.write_gatt_char(write_uuid, _STATUS_CMD, response=True)
                reply = await client.read_gatt_char(reply_uuid)
                _LOGGER.debug(
                    "Status reply: %s (len=%d)",
                    reply.hex() if reply else "None",
                    len(reply) if reply else 0,
                )
                if reply and len(reply) >= 3:
                    result["status_code"] = reply[2]
                if reply and len(reply) >= 32:
                    result.update(parse_status_info(reply))
            except Exception as err:
                _LOGGER.debug("Status request failed: %s", err)

            result["online"] = True
            _LOGGER.debug("Printer data: %s", result)

    except (BleakError, TimeoutError, OSError) as err:
        _LOGGER.debug("Connection failed: %s", err)
        return {}

    return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DYMO LetraTag sensors from a config entry."""
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "DYMO LetraTag")

    # Shared state: all sensors read from this dict, updated when
    # the printer comes online (detected via BLE advertisement).
    status_data: dict[str, Any] = {}
    entities: list[LetraTagSensorBase] = [
        LetraTagStatusSensor(entry, address, name, status_data),
        LetraTagFirmwareSensor(entry, address, name, status_data),
    ]
    async_add_entities(entities)

    # Track whether we already fetched status for this "online" period
    # to avoid repeated connections while the printer keeps advertising.
    fetched_this_session: dict[str, bool] = {"done": False}

    @callback
    def _on_advertisement(
        service_info: BluetoothServiceInfoBleak,
        change: Any,
    ) -> None:
        """Printer advertisement detected - it's on. Fetch status."""
        if fetched_this_session["done"]:
            return
        fetched_this_session["done"] = True
        _LOGGER.debug("Printer %s is online, fetching status", address)
        hass.async_create_task(_fetch_and_update())

    async def _fetch_and_update() -> None:
        data = await _read_printer_status(hass, address)
        if data:
            status_data.clear()
            status_data.update(data)
            _LOGGER.debug("Status updated: %s", data)
            for entity in entities:
                entity.async_write_ha_state()

    @callback
    def _on_unavailable(
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Printer went offline. Reset fetch flag for next wake."""
        _LOGGER.debug("Printer %s went offline", address)
        fetched_this_session["done"] = False

    # Register for advertisements from this specific address
    entry.async_on_unload(
        async_register_callback(
            hass,
            _on_advertisement,
            BluetoothCallbackMatcher(address=address),
            BluetoothScanningMode.ACTIVE,
        )
    )

    # Register for unavailable notifications
    entry.async_on_unload(
        bluetooth.async_track_unavailable(
            hass,
            _on_unavailable,
            address,
            connectable=True,
        )
    )


class LetraTagSensorBase(SensorEntity):
    """Base class for LetraTag sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        address: str,
        device_name: str,
        status_data: dict[str, Any],
    ) -> None:
        self._entry = entry
        self._address = address
        self._device_name = device_name
        self._status_data = status_data

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=self._device_name,
            manufacturer="DYMO",
            model="LetraTag 200B",
        )

    @property
    def available(self) -> bool:
        return bool(self._status_data)


class LetraTagStatusSensor(LetraTagSensorBase):
    """Printer status sensor."""

    _attr_name = "Status"
    _attr_icon = "mdi:printer"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_status"

    @property
    def native_value(self) -> str | None:
        if not self._status_data:
            return None
        error = self._status_data.get("error")
        if error and isinstance(error, dict) and error.get("key", 0) != 0:
            return error.get("value", "Error")
        code = self._status_data.get("status_code")
        if code is not None and code != 0:
            return f"Status {code}"
        return "Ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._status_data:
            return {}
        attrs = {}
        for k in (
            "manufacturer",
            "model",
            "serial",
            "firmware",
            "hardware_revision",
        ):
            if k in self._status_data:
                attrs[k] = self._status_data[k]
        return attrs


class LetraTagFirmwareSensor(LetraTagSensorBase):
    """Firmware version sensor."""

    _attr_name = "Firmware"
    _attr_icon = "mdi:chip"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_firmware"

    @property
    def native_value(self) -> str | None:
        return self._status_data.get("firmware")
