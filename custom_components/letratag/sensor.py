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

Provides sensors for battery level, cassette type, and printer status
by parsing BLE advertisement manufacturer data.
"""

from __future__ import annotations

import logging
from typing import Any

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

from .const import DOMAIN, TAPE_SIZES
from .protocol import parse_manufacturer_data

_LOGGER = logging.getLogger(__name__)

# Map battery_level field (0-3) to percentage
_BATTERY_MAP = {0: 10, 1: 40, 2: 70, 3: 100}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DYMO LetraTag sensors from a config entry."""
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "DYMO LetraTag")

    entities = [
        LetraTagBatterySensor(entry, address, name),
        LetraTagCassetteSensor(entry, address, name),
        LetraTagStatusSensor(entry, address, name),
    ]
    async_add_entities(entities)


class LetraTagSensorBase(SensorEntity):
    """Base class for LetraTag sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        address: str,
        device_name: str,
    ) -> None:
        self._entry = entry
        self._address = address
        self._device_name = device_name
        self._adv_data: dict[str, Any] = {}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=self._device_name,
            manufacturer="DYMO",
            model="LetraTag 200B",
        )

    async def async_added_to_hass(self) -> None:
        """Register BLE advertisement callback."""
        _LOGGER.debug(
            "Registering BLE callback for %s (%s)",
            self._device_name,
            self._address,
        )

        @callback
        def _handle_update(
            service_info: BluetoothServiceInfoBleak,
            change: Any,
        ) -> None:
            _LOGGER.debug(
                "BLE callback: addr=%s name=%s mfr_data=%s service_uuids=%s",
                service_info.address,
                service_info.name,
                {k: v.hex() for k, v in service_info.manufacturer_data.items()}
                if service_info.manufacturer_data
                else None,
                service_info.service_uuids,
            )

            if service_info.address.upper() != self._address.upper():
                return

            mfr_data = service_info.manufacturer_data
            if not mfr_data:
                _LOGGER.debug("No manufacturer data for %s", self._address)
                return

            for company_id, raw in mfr_data.items():
                _LOGGER.debug(
                    "Parsing manufacturer data: company=0x%04x raw=%s len=%d",
                    company_id,
                    raw.hex(),
                    len(raw),
                )
                parsed = parse_manufacturer_data(raw)
                if parsed:
                    _LOGGER.debug("Parsed: %s", parsed)
                    self._adv_data = parsed
                    self.async_write_ha_state()
                break

        self.async_on_remove(
            async_register_callback(
                self.hass,
                _handle_update,
                BluetoothCallbackMatcher(
                    connectable=True,
                ),
                BluetoothScanningMode.ACTIVE,
            )
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
        level = self._adv_data.get("battery_level")
        if level is None:
            return None
        return _BATTERY_MAP.get(level)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {}
        if self._adv_data.get("charging"):
            attrs["charging"] = True
        if self._adv_data.get("battery_low"):
            attrs["battery_low"] = True
        if self._adv_data.get("battery_too_low"):
            attrs["battery_too_low"] = True
        return attrs


class LetraTagCassetteSensor(LetraTagSensorBase):
    """Cassette type sensor."""

    _attr_name = "Cassette"
    _attr_icon = "mdi:label-outline"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_cassette"

    @property
    def native_value(self) -> str | None:
        cassette_id = self._adv_data.get("cassette_id")
        if cassette_id is None:
            return None
        return TAPE_SIZES.get(cassette_id, f"Unknown ({cassette_id})")


class LetraTagStatusSensor(LetraTagSensorBase):
    """Printer status sensor."""

    _attr_name = "Status"
    _attr_icon = "mdi:printer"

    @property
    def unique_id(self) -> str:
        return f"{self._address}_status"

    @property
    def native_value(self) -> str:
        if not self._adv_data:
            return "Unknown"

        if self._adv_data.get("busy"):
            return "Busy"
        if self._adv_data.get("tape_jam"):
            return "Tape jam"
        if self._adv_data.get("cutter_jam"):
            return "Cutter jam"
        if self._adv_data.get("battery_too_low"):
            return "Battery too low"
        return "Ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._adv_data:
            return {}
        return {
            "revision": self._adv_data.get("revision"),
            "busy": self._adv_data.get("busy"),
            "charging": self._adv_data.get("charging"),
        }
