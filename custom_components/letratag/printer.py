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
    ble_uuid,
    PRINT_REPLY_UUID,
    PRINT_REQUEST_UUID,
    SERVICE_UUID,
)
from .protocol import (
    ProtocolStream,
    build_print_stream,
    build_status_direct,
    parse_manufacturer_data,
    parse_notification,
)
from .render import prepare_print_data, render_text

_LOGGER = logging.getLogger(__name__)


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
        self._last_response: int | None = None
        self._response_event = asyncio.Event()

    def _notification_handler(self, _sender: Any, data: bytearray) -> None:
        """Handle BLE notification from the printer."""
        code = parse_notification(data)
        self._last_response = code
        self._response_event.set()
        msg = RESPONSE_MESSAGES.get(code, f"Unknown ({code})")
        _LOGGER.debug("Printer notification: %s (code=%d)", msg, code)

    async def _write_stream(self, client: BleakClient, stream: ProtocolStream) -> None:
        """Write a protocol stream to the printer."""
        # Write header
        await client.write_gatt_char(self._write_uuid, stream.header)

        # Write body chunks
        for chunk in stream.body_chunks:
            await client.write_gatt_char(self._write_uuid, chunk)

    async def print_label(
        self,
        text: str,
        copies: int = 1,
        cut: bool = True,
        font_path: str | None = None,
        font_size: int | None = None,
        ble_device: Any | None = None,
    ) -> str:
        """Print a text label.

        Args:
            text: Text to print. Use newlines for multi-line labels.
            copies: Number of copies (1-255).
            cut: Whether to cut the tape after printing.
            font_path: Optional path to a .ttf font file.
            font_size: Optional font size in pixels.
            ble_device: Optional BleakDevice from HA bluetooth.

        Returns:
            Status message string.

        Raises:
            PrintError: If the print operation fails.
        """
        img = render_text(
            text,
            label_height=LABEL_HEIGHT,
            font_path=font_path,
            font_size=font_size,
        )
        return await self.print_image(
            img, copies=copies, cut=cut, ble_device=ble_device
        )

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

        Returns a status message string.
        """
        self._last_response = None
        self._response_event.clear()

        target = ble_device if ble_device is not None else self.address

        try:
            async with BleakClient(target, timeout=CONNECT_TIMEOUT) as client:
                _LOGGER.debug("Connected to %s", self.address)

                # Subscribe to notifications
                await client.start_notify(self._notify_uuid, self._notification_handler)

                # Send print data
                await self._write_stream(client, stream)
                _LOGGER.debug("Print data sent, waiting for response")

                # Wait for printer response
                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    raise PrintError("Printer response timeout")

                await client.stop_notify(self._notify_uuid)

        except BleakError as err:
            raise PrintError(f"BLE error: {err}") from err

        code = self._last_response
        if code is None:
            raise PrintError("No response from printer")

        msg = RESPONSE_MESSAGES.get(code, f"Unknown response ({code})")

        if code in (RESPONSE_SUCCESS, RESPONSE_SUCCESS_LOW_BATTERY):
            _LOGGER.info("Print complete: %s", msg)
            return msg

        raise PrintError(msg)

    async def request_status(self, ble_device: Any | None = None) -> dict:
        """Send a status request and return parsed manufacturer data.

        This is a lightweight operation that connects briefly to
        query the printer state.
        """
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
    def parse_advertisement(manufacturer_data: dict[int, bytes]) -> dict:
        """Parse manufacturer data from a BLE advertisement."""
        for _company_id, data in manufacturer_data.items():
            return parse_manufacturer_data(data)
        return {}
