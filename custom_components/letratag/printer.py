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
printer using bleak via HA's bluetooth integration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from .const import (
    DEFAULT_DEVICE_UUID,
    LABEL_HEIGHT,
    LABEL_HEIGHT_PADDED,
    PRINT_REPLY_UUID,
    PRINT_REQUEST_UUID,
    RESPONSE_MESSAGES,
    RESPONSE_PRINTING,
    RESPONSE_SUCCESS,
    RESPONSE_SUCCESS_LOW_BATTERY,
    SERVICE_UUID,
    ble_uuid,
)
from .protocol import ProtocolStream, build_print_stream, parse_notification

_LOGGER = logging.getLogger(__name__)

# Maximum retries for transient BLE write failures
_WRITE_RETRIES = 2

# The job reply only comes once the label is printed. A LetraTag 200B took
# 4.3s for the 150 rasterline minimum and 25s for 2000 rasterlines, about
# 11ms a rasterline, so allow a fixed delay plus some margin per rasterline.
_REPLY_TIMEOUT_BASE = 10.0
_REPLY_TIMEOUT_PER_LINE = 0.015

_LINK_LOST = "Lost the Bluetooth connection to the printer (out of range or off)"


class PrintError(Exception):
    """Raised when a print operation fails."""


class LetraTagPrinter:
    """BLE client for the DYMO LetraTag printer."""

    def __init__(self, address: str, device_uuid: str = DEFAULT_DEVICE_UUID) -> None:
        self.address = address
        self._device_uuid = device_uuid
        self._service_uuid = ble_uuid(SERVICE_UUID, device_uuid)
        self._write_uuid = ble_uuid(PRINT_REQUEST_UUID, device_uuid)
        self._notify_uuid = ble_uuid(PRINT_REPLY_UUID, device_uuid)
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        """Guard for BLE access, the printer takes one connection at a time."""
        return self._lock

    async def _write_char(self, client: BleakClient, data: bytes | bytearray) -> None:
        """Write to the print request characteristic with retry.

        Uses write-with-response (the Android app's default via
        BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT). BlueZ
        handles ATT segmentation for payloads exceeding the MTU.
        """
        last_err: Exception | None = None
        for attempt in range(_WRITE_RETRIES + 1):
            try:
                await client.write_gatt_char(self._write_uuid, data, response=True)
                return
            except (BleakError, EOFError, TimeoutError) as err:
                # A write cannot succeed on a dropped link, and bleak then
                # reports errors that say nothing about the cause
                if not client.is_connected:
                    raise PrintError(_LINK_LOST) from err
                last_err = err
                if attempt < _WRITE_RETRIES:
                    _LOGGER.debug(
                        "Write failed (attempt %d/%d): %s",
                        attempt + 1,
                        _WRITE_RETRIES + 1,
                        err,
                    )
                    await asyncio.sleep(0.1)
        raise last_err  # type: ignore[misc]

    async def _write_stream(self, client: BleakClient, stream: ProtocolStream) -> None:
        """Write a protocol stream to the printer."""
        _LOGGER.debug(
            "Sending: header=%d bytes, %d chunks",
            len(stream.header),
            len(stream.body_chunks),
        )
        await self._write_char(client, stream.header)
        for i, chunk in enumerate(stream.body_chunks):
            await self._write_char(client, chunk)
            if (i + 1) % 10 == 0:
                _LOGGER.debug("Sent chunk %d/%d", i + 1, len(stream.body_chunks))

    async def print_image(
        self,
        img: Any,
        ble_device: BLEDevice,
        copies: int = 1,
        cut: bool | None = None,
    ) -> str:
        """Print a PIL Image.

        Args:
            img: PIL Image object.
            ble_device: BLEDevice from HA bluetooth.
            copies: Number of copies (1-255).
            cut: None for FormFeed (no cutter), True to cut, False to feed
                without cutting (cutter-equipped models only).

        Returns:
            Status message string.

        Raises:
            PrintError: If the print operation fails.
        """
        from .render import prepare_print_data

        # Rasterizing is CPU bound (per pixel loops and a resize), so keep it
        # off the event loop.
        loop = asyncio.get_running_loop()
        width, print_data = await loop.run_in_executor(
            None, prepare_print_data, img, LABEL_HEIGHT
        )
        _LOGGER.debug("Print data: %d rasterlines, %d bytes", width, len(print_data))

        # The LetraTag 200B ignores the copies command and prints one label,
        # so the job goes out once per copy instead.
        stream = build_print_stream(
            print_data=print_data,
            width=width,
            cut=cut,
            label_height_padded=LABEL_HEIGHT_PADDED,
        )

        reply_timeout = _REPLY_TIMEOUT_BASE + _REPLY_TIMEOUT_PER_LINE * width
        return await self._send_stream(stream, ble_device, reply_timeout, copies)

    async def _send_stream(
        self,
        stream: ProtocolStream,
        ble_device: BLEDevice,
        reply_timeout: float,
        copies: int,
    ) -> str:
        """Connect, send the stream once per copy, wait for each reply."""
        async with self._lock:
            response_event = asyncio.Event()
            last_response: list[int | None] = [None]
            # The printer pushes its idle reply as soon as notifications are
            # enabled, before any job is sent. Like the app, only take the
            # replies that arrive once the whole job is written.
            job_sent = asyncio.Event()
            result = ""

            def _on_disconnect(_client: BleakClient) -> None:
                # Stop waiting for a reply that can no longer arrive. Drops
                # before that are failed connect attempts or failed writes.
                if job_sent.is_set():
                    response_event.set()

            def _notification_handler(_sender: Any, data: bytearray) -> None:
                if not job_sent.is_set():
                    _LOGGER.debug("Ignoring reply sent before the job: %s", data.hex())
                    return
                code = parse_notification(data)
                last_response[0] = code
                response_event.set()
                msg = RESPONSE_MESSAGES.get(code, f"Unknown ({code})")
                _LOGGER.debug("Printer notification: %s (code=%d)", msg, code)

            client: BleakClient | None = None
            try:
                _LOGGER.debug("Connecting to %s", self.address)
                client = await establish_connection(
                    BleakClient,
                    ble_device,
                    self.address,
                    disconnected_callback=_on_disconnect,
                )
                _LOGGER.debug("Connected, MTU=%d", client.mtu_size)

                for service in client.services:
                    for char in service.characteristics:
                        _LOGGER.debug(
                            "  %s: %s",
                            char.uuid,
                            char.properties,
                        )

                await client.start_notify(self._notify_uuid, _notification_handler)

                for copy in range(1, copies + 1):
                    job_sent.clear()
                    response_event.clear()
                    last_response[0] = None

                    await self._write_stream(client, stream)
                    job_sent.set()
                    if not client.is_connected:
                        raise PrintError(_LINK_LOST)
                    _LOGGER.debug(
                        "Copy %d/%d sent, waiting up to %.0fs for the reply",
                        copy,
                        copies,
                        reply_timeout,
                    )

                    try:
                        await asyncio.wait_for(
                            response_event.wait(), timeout=reply_timeout
                        )
                    except asyncio.TimeoutError:
                        raise PrintError("Printer response timeout")
                    if last_response[0] is None:
                        raise PrintError(_LINK_LOST)
                    result = _reply_result(last_response[0])

                await client.stop_notify(self._notify_uuid)

            except PrintError:
                raise
            except BleakError as err:
                _LOGGER.exception("BLE error")
                raise PrintError(f"BLE error: {err}") from err
            except Exception as err:
                _LOGGER.exception("Unexpected error")
                raise PrintError(f"Error: {err}") from err
            finally:
                if client is not None and client.is_connected:
                    await client.disconnect()

        _LOGGER.info("Print complete: %s", result)
        return result


def _reply_result(code: int) -> str:
    """Name a job reply, raising PrintError when the job failed."""
    msg = RESPONSE_MESSAGES.get(code, f"Unknown response ({code})")

    # The Genie firmware reports an accepted job with code 1 (Printing).
    # The LetraTag Connect app treats that code as the terminal success
    # state and disconnects, so it is a success here as well.
    if code in (RESPONSE_SUCCESS, RESPONSE_PRINTING, RESPONSE_SUCCESS_LOW_BATTERY):
        return msg

    raise PrintError(msg)
