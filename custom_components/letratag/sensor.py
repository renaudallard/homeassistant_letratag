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

Provides sensors for battery level, cassette type, and printer status.
Since the LetraTag does not include manufacturer data in its BLE
advertisements, status is read via GATT by connecting periodically.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONNECT_TIMEOUT,
    DOMAIN,
    PRINT_REPLY_UUID,
    PRINT_REQUEST_UUID,
    ble_uuid,
)
from .protocol import parse_status_info

_LOGGER = logging.getLogger(__name__)

# Poll interval for status reads
_POLL_INTERVAL = timedelta(minutes=5)

# Map battery_level field (0-3) to percentage
_BATTERY_MAP = {0: 10, 1: 40, 2: 70, 3: 100}

# Status command: ESC + 'A' + 0x00
_STATUS_CMD = bytes([0x1B, 0x41, 0x00])


async def _read_printer_status(hass: HomeAssistant, address: str) -> dict[str, Any]:
    """Connect to the printer and read status via GATT."""
    write_uuid = ble_uuid(PRINT_REQUEST_UUID)
    reply_uuid = ble_uuid(PRINT_REPLY_UUID)

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is None:
        _LOGGER.debug("Printer %s not found in BLE scanner", address)
        return {}

    try:
        async with BleakClient(ble_device, timeout=CONNECT_TIMEOUT) as client:
            # Write status request
            await client.write_gatt_char(write_uuid, _STATUS_CMD, response=True)
            # Read reply
            data = await client.read_gatt_char(reply_uuid)
            _LOGGER.debug(
                "Status response from %s: %s (len=%d)",
                address,
                data.hex() if data else "None",
                len(data) if data else 0,
            )
            if data and len(data) >= 32:
                return parse_status_info(data)
            _LOGGER.debug(
                "Status response too short: %d bytes", len(data) if data else 0
            )
            return {}
    except (BleakError, TimeoutError, OSError) as err:
        _LOGGER.debug("Status read failed for %s: %s", address, err)
        return {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DYMO LetraTag sensors from a config entry."""
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "DYMO LetraTag")

    async def _update() -> dict[str, Any]:
        data = await _read_printer_status(hass, address)
        if not data:
            raise UpdateFailed("Could not read printer status")
        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{name} status",
        update_method=_update,
        update_interval=_POLL_INTERVAL,
    )

    # Do first refresh; if it fails, sensors start as unavailable
    await coordinator.async_config_entry_first_refresh()

    entities = [
        LetraTagBatterySensor(coordinator, entry, address, name),
        LetraTagCassetteSensor(coordinator, entry, address, name),
        LetraTagStatusSensor(coordinator, entry, address, name),
    ]
    async_add_entities(entities)


class LetraTagSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for LetraTag sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        address: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._address = address
        self._device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=self._device_name,
            manufacturer="DYMO",
            model="LetraTag 200B",
        )


class LetraTagBatterySensor(LetraTagSensorBase):
    """Battery level sensor."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._address}_battery"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        level = self.coordinator.data.get("battery_level")
        if level is None:
            return None
        return _BATTERY_MAP.get(level)


class LetraTagCassetteSensor(LetraTagSensorBase):
    """Cassette type sensor."""

    _attr_name = "Cassette"
    _attr_icon = "mdi:label-outline"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_cassette"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        sku = self.coordinator.data.get("sku")
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
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        error = self.coordinator.data.get("error")
        if error and isinstance(error, dict) and error.get("key", 0) != 0:
            return error.get("value", "Error")
        status = self.coordinator.data.get("print_status", 0)
        if status == 0:
            return "Ready"
        return f"Status {status}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {
            k: v
            for k, v in self.coordinator.data.items()
            if k
            in (
                "cutter_status",
                "main_bay_status",
                "label_count",
                "eps_charging",
            )
        }
