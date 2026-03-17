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

"""DYMO LetraTag BLE printer client.

Handles the BLE connection lifecycle and data transmission to the
printer using bleak. Designed for use within Home Assistant but has
no direct HA dependencies beyond the BLE device handle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError

from .const import (
    CONNECT_TIMEOUT,
    LABEL_HEIGHT,
    LABEL_HEIGHT_PADDED,
    RESPONSE_MESSAGES,
    RESPONSE_SUCCESS,
    RESPONSE_SUCCESS_LOW_BATTERY,
    PRINT_REPLY_UUID,
    PRINT_REQUEST_UUID,
    SERVICE_UUID,
    ble_uuid,
)
from .protocol import (
    ProtocolStream,
    build_print_stream,
    build_status_direct,
    parse_manufacturer_data,
    parse_notification,
)

_LOGGER = logging.getLogger(__name__)

# Desired MTU for large chunk writes (app uses autoMaxMTU)
_DESIRED_MTU = 512


class PrintError(Exception):
    """Raised when a print operation fails."""


class LetraTagPrinter:
    """BLE client for the DYMO LetraTag printer."""

    def __init__(self, address: str, device_uuid: str = "2b3d") -> None:
        self.address = address
        self._device_uuid = device_uuid
        self._service_uuid = ble_uuid(SERVICE_UUID, device_uuid)
        self._write_uuid = ble_uuid(PRINT_REQUEST_UUID, device_uuid)
        self._notify_uuid = ble_uuid(PRINT_REPLY_UUID, device_uuid)
        self._print_lock = asyncio.Lock()

    async def _request_mtu(self, client: BleakClient) -> int:
        """Request a larger MTU for bulk data transfer.

        The DYMO app uses autoMaxMTU=true which negotiates the maximum.
        Returns the negotiated MTU size.
        """
        try:
            mtu = client.mtu_size
            _LOGGER.debug("Initial MTU: %d", mtu)
            if mtu < _DESIRED_MTU:
                # On BlueZ, requesting MTU is done via the backend
                backend = getattr(client, "_backend", None)
                if backend and hasattr(backend, "_acquire_mtu"):
                    mtu = await backend._acquire_mtu()
                    _LOGGER.debug("Negotiated MTU: %d", mtu)
                elif backend and hasattr(backend, "request_mtu"):
                    mtu = await backend.request_mtu(_DESIRED_MTU)
                    _LOGGER.debug("Requested MTU: %d", mtu)
            return mtu
        except Exception as err:
            _LOGGER.debug("MTU negotiation failed: %s", err)
            return client.mtu_size

    async def _write_stream(self, client: BleakClient, stream: ProtocolStream) -> None:
        """Write a protocol stream to the printer.

        Header is written with response (reliable delivery).
        Body chunks use write-without-response for throughput,
        matching the app's bulk transfer behavior.
        """
        # Write header with response
        await client.write_gatt_char(self._write_uuid, stream.header, response=True)

        # Write body chunks without response for speed
        for chunk in stream.body_chunks:
            await client.write_gatt_char(self._write_uuid, chunk, response=False)

    async def print_image(
        self,
        img: Any,
        copies: int = 1,
        cut: bool = True,
        ble_device: Any | None = None,
    ) -> str:
        """Print a PIL Image.

        Args:
            img: PIL Image object.
            copies: Number of copies (1-255).
            cut: Whether to cut the tape after printing.
            ble_device: Optional BleakDevice from HA bluetooth.

        Returns:
            Status message string.

        Raises:
            PrintError: If the print operation fails.
        """
        from .render import prepare_print_data

        width, print_data = prepare_print_data(img, LABEL_HEIGHT)

        stream = build_print_stream(
            print_data=print_data,
            width=width,
            copies=copies,
            cut=cut,
            label_height_padded=LABEL_HEIGHT_PADDED,
        )

        return await self._send_stream(stream, ble_device)

    async def _send_stream(
        self,
        stream: ProtocolStream,
        ble_device: Any | None = None,
    ) -> str:
        """Connect, send a protocol stream, wait for response, disconnect.

        Uses a lock to prevent concurrent print jobs from corrupting
        shared notification state.
        """
        async with self._print_lock:
            response_event = asyncio.Event()
            last_response: list[int | None] = [None]

            def _notification_handler(_sender: Any, data: bytearray) -> None:
                code = parse_notification(data)
                last_response[0] = code
                response_event.set()
                msg = RESPONSE_MESSAGES.get(code, f"Unknown ({code})")
                _LOGGER.debug("Printer notification: %s (code=%d)", msg, code)

            target = ble_device if ble_device is not None else self.address

            try:
                async with BleakClient(target, timeout=CONNECT_TIMEOUT) as client:
                    _LOGGER.debug("Connected to %s", self.address)

                    # Negotiate max MTU for 500-byte chunks
                    mtu = await self._request_mtu(client)
                    _LOGGER.debug("Using MTU: %d", mtu)

                    await client.start_notify(self._notify_uuid, _notification_handler)

                    await self._write_stream(client, stream)
                    _LOGGER.debug("Print data sent, waiting for response")

                    try:
                        await asyncio.wait_for(response_event.wait(), timeout=30.0)
                    except asyncio.TimeoutError:
                        raise PrintError("Printer response timeout")

                    await client.stop_notify(self._notify_uuid)

            except BleakError as err:
                raise PrintError(f"BLE error: {err}") from err

        code = last_response[0]
        if code is None:
            raise PrintError("No response from printer")

        msg = RESPONSE_MESSAGES.get(code, f"Unknown response ({code})")

        if code in (RESPONSE_SUCCESS, RESPONSE_SUCCESS_LOW_BATTERY):
            _LOGGER.info("Print complete: %s", msg)
            return msg

        raise PrintError(msg)

    async def request_status(self, ble_device: Any | None = None) -> dict:
        """Send a status request and return parsed manufacturer data."""
        target = ble_device if ble_device is not None else self.address

        try:
            async with BleakClient(target, timeout=CONNECT_TIMEOUT) as client:
                await client.write_gatt_char(self._write_uuid, build_status_direct())
                data = await client.read_gatt_char(self._notify_uuid)
                return parse_manufacturer_data(data)
        except BleakError as err:
            _LOGGER.error("Status request failed: %s", err)
            return {}

    @staticmethod
    def parse_advertisement(
        manufacturer_data: dict[int, bytes],
    ) -> dict:
        """Parse manufacturer data from a BLE advertisement."""
        for _company_id, data in manufacturer_data.items():
            return parse_manufacturer_data(data)
        return {}
