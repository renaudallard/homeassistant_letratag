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

Supports two data sources depending on the printer model/firmware:
1. BLE advertisement manufacturer data (battery, cassette, errors)
2. GATT connection (device info, status command reply)

Both paths feed into a shared data dict. Whichever source provides
data, the sensors display it. Advertisement data is passive (no
connection needed). GATT data is fetched once when the printer
comes online.
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
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONNECT_TIMEOUT,
    DOMAIN,
    PRINT_REPLY_UUID,
    PRINT_REQUEST_UUID,
    TAPE_SIZES,
    ble_uuid,
)
from .protocol import parse_manufacturer_data, parse_status_info

_LOGGER = logging.getLogger(__name__)

_BATTERY_MAP = {0: 10, 1: 40, 2: 70, 3: 100}
_STATUS_CMD = bytes([0x1B, 0x41, 0x00])

# GATT Device Information Service characteristic UUIDs (fragments)
_DIS_CHARS = {
    "00002a29": "manufacturer",
    "00002a24": "model",
    "00002a25": "serial",
    "00002a26": "firmware",
    "00002a27": "hardware_revision",
}


async def _read_gatt_status(hass: HomeAssistant, address: str) -> dict[str, Any]:
    """Connect to the printer and read GATT data.

    Reads Device Information Service characteristics and sends
    the ESC-A status command. Returns whatever data is available.
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
            # Read Device Information Service characteristics
            for service in client.services:
                for char in service.characteristics:
                    if "read" not in char.properties:
                        continue
                    for uuid_frag, key in _DIS_CHARS.items():
                        if uuid_frag in char.uuid:
                            try:
                                data = await client.read_gatt_char(char.uuid)
                                result[key] = data.decode(
                                    "utf-8", errors="replace"
                                ).strip()
                            except Exception as err:
                                _LOGGER.debug(
                                    "Cannot read %s: %s",
                                    char.uuid,
                                    err,
                                )
                            break

            # Send status request and read reply
            try:
                await client.write_gatt_char(write_uuid, _STATUS_CMD, response=True)
                reply = await client.read_gatt_char(reply_uuid)
                if reply and len(reply) >= 3:
                    result["status_code"] = reply[2]
                if reply and len(reply) >= 32:
                    result.update(parse_status_info(reply))
            except Exception as err:
                _LOGGER.debug("Status request failed: %s", err)

            result["online"] = True

    except (BleakError, TimeoutError, OSError) as err:
        _LOGGER.debug("GATT connection failed: %s", err)
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

    # Shared state dict fed by both advertisement and GATT data
    status_data: dict[str, Any] = {}

    entities: list[LetraTagSensorBase] = [
        LetraTagBatterySensor(entry, address, name, status_data),
        LetraTagCassetteSensor(entry, address, name, status_data),
        LetraTagStatusSensor(entry, address, name, status_data),
        LetraTagFirmwareSensor(entry, address, name, status_data),
    ]
    async_add_entities(entities)

    fetched_this_session: dict[str, bool] = {"done": False}

    def _update_entities() -> None:
        for entity in entities:
            entity.async_write_ha_state()

    @callback
    def _on_advertisement(
        service_info: BluetoothServiceInfoBleak,
        change: Any,
    ) -> None:
        """Handle BLE advertisement from the printer."""
        # Parse manufacturer data if present (some models broadcast it)
        mfr_data = service_info.manufacturer_data
        if mfr_data:
            for _company_id, raw in mfr_data.items():
                parsed = parse_manufacturer_data(raw)
                if parsed:
                    status_data.update(parsed)
                    status_data["online"] = True
                    _update_entities()
                break

        # Fetch GATT data once per online session
        if not fetched_this_session["done"]:
            fetched_this_session["done"] = True
            _LOGGER.debug("Printer %s is online, fetching GATT data", address)
            hass.async_create_task(_fetch_gatt())

    async def _fetch_gatt() -> None:
        data = await _read_gatt_status(hass, address)
        if data:
            status_data.update(data)
            _update_entities()

    @callback
    def _on_unavailable(
        service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Printer went offline."""
        _LOGGER.debug("Printer %s went offline", address)
        fetched_this_session["done"] = False
        status_data.clear()
        _update_entities()

    entry.async_on_unload(
        async_register_callback(
            hass,
            _on_advertisement,
            BluetoothCallbackMatcher(address=address),
            BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(
        bluetooth.async_track_unavailable(
            hass, _on_unavailable, address, connectable=True
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


class LetraTagBatterySensor(LetraTagSensorBase):
    """Battery level sensor. Available on models that broadcast it."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._address}_battery"

    @property
    def available(self) -> bool:
        # Only available if we have battery data from any source
        return (
            self._status_data.get("battery_level") is not None
            or self._status_data.get("battery_level_raw") is not None
        )

    @property
    def native_value(self) -> int | None:
        raw = self._status_data.get("battery_level_raw")
        if raw is not None:
            return raw
        level = self._status_data.get("battery_level")
        if level is None:
            return None
        return _BATTERY_MAP.get(level)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {}
        if self._status_data.get("charging"):
            attrs["charging"] = True
        if self._status_data.get("battery_low"):
            attrs["battery_low"] = True
        if self._status_data.get("battery_too_low"):
            attrs["battery_too_low"] = True
        return attrs


class LetraTagCassetteSensor(LetraTagSensorBase):
    """Cassette type sensor. Available on models that report it."""

    _attr_name = "Cassette"
    _attr_icon = "mdi:label-outline"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_cassette"

    @property
    def available(self) -> bool:
        return (
            self._status_data.get("cassette_id") is not None
            or self._status_data.get("sku") is not None
        )

    @property
    def native_value(self) -> str | None:
        # From advertisement manufacturer data
        cassette_id = self._status_data.get("cassette_id")
        if cassette_id is not None:
            return TAPE_SIZES.get(cassette_id, f"Unknown ({cassette_id})")
        # From extended GATT status response
        sku = self._status_data.get("sku")
        if sku and isinstance(sku, dict):
            return sku.get("value", "Unknown")
        return None


class LetraTagStatusSensor(LetraTagSensorBase):
    """Printer status sensor."""

    _attr_name = "Status"
    _attr_icon = "mdi:printer"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_status"

    @property
    def available(self) -> bool:
        return bool(self._status_data.get("online"))

    @property
    def native_value(self) -> str | None:
        if not self._status_data:
            return None
        # Advertisement error flags
        if self._status_data.get("busy"):
            return "Busy"
        if self._status_data.get("tape_jam"):
            return "Tape jam"
        if self._status_data.get("cutter_jam"):
            return "Cutter jam"
        if self._status_data.get("battery_too_low"):
            return "Battery too low"
        # Extended GATT error
        error = self._status_data.get("error")
        if error and isinstance(error, dict) and error.get("key", 0) != 0:
            return error.get("value", "Error")
        # Short GATT status code
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
            "revision",
            "cutter_status",
            "main_bay_status",
            "label_count",
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
    def available(self) -> bool:
        return self._status_data.get("firmware") is not None

    @property
    def native_value(self) -> str | None:
        return self._status_data.get("firmware")
