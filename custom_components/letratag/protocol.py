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

"""DYMO LetraTag BLE print protocol.

Implements the command encoding, communication framing, and response
parsing reverse-engineered from the DYMO LetraTag Connect 2.1.0 app.

Protocol overview:
  - Commands are ESC (0x1B) prefixed with a single-char command code.
  - Multiple commands are concatenated into a body buffer.
  - The body is wrapped in a CommunicationProtocolStream with a 9-byte
    header and the body split into 500-byte chunks.
  - Each chunk is prefixed with a 1-byte sequence number (skipping 27/ESC).
  - The last chunk has magic bytes (0x12 0x34) appended.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    ALIGNMENT_CENTER,
    BODY_CHUNK_SIZE,
    BPP_MONO,
    CMD_COPIES,
    CMD_CUT,
    CMD_END,
    CMD_FORM_FEED,
    CMD_MEDIA_TYPE,
    CMD_PRINT_DATA,
    CMD_START,
    CMD_STATUS,
    CUT_TAPE,
    DEFAULT_JOB_ID,
    ESC,
    FLAGS,
    LABEL_HEIGHT_PADDED,
    MAGIC,
    NO_CUT,
    PREAMBLE,
    TAPE_SIZES,
)


def _cmd(code: int) -> bytes:
    """Build a 2-byte ESC + command prefix."""
    return bytes([ESC, code])


def build_start_job(job_id: bytes = DEFAULT_JOB_ID) -> bytes:
    """Build StartJob command (6 bytes)."""
    buf = bytearray(6)
    buf[0] = ESC
    buf[1] = CMD_START
    buf[2 : 2 + len(job_id)] = job_id
    return bytes(buf)


def build_media_type(media_id: int) -> bytes:
    """Build MediaType command (6 bytes)."""
    buf = bytearray(6)
    buf[0] = ESC
    buf[1] = CMD_MEDIA_TYPE
    buf[2] = media_id & 0xFF
    return bytes(buf)


def build_copies(n: int) -> bytes:
    """Build NumberOfCopies command (3 bytes)."""
    return bytes([ESC, CMD_COPIES, n & 0xFF])


def build_print_data(
    width: int,
    height: int,
    print_data: bytes,
    bpp: int = BPP_MONO,
    alignment: int = ALIGNMENT_CENTER,
) -> bytes:
    """Build PrintData command (12 + len(print_data) bytes)."""
    buf = bytearray(12 + len(print_data))
    buf[0] = ESC
    buf[1] = CMD_PRINT_DATA
    buf[2] = bpp
    buf[3] = alignment
    buf[4:8] = width.to_bytes(4, "little")
    buf[8:12] = height.to_bytes(4, "little")
    buf[12:] = print_data
    return bytes(buf)


def build_cut(cut: bool = True) -> bytes:
    """Build Cut command (3 bytes)."""
    return bytes([ESC, CMD_CUT, CUT_TAPE if cut else NO_CUT])


def build_form_feed() -> bytes:
    """Build FormFeed command (2 bytes)."""
    return _cmd(CMD_FORM_FEED)


def build_status_request() -> bytes:
    """Build Status command (2 bytes)."""
    return _cmd(CMD_STATUS)


def build_end_job() -> bytes:
    """Build EndJob command (2 bytes)."""
    return _cmd(CMD_END)


def build_status_direct() -> bytes:
    """Build a direct status write (3 bytes, no stream wrapping)."""
    return bytes([ESC, CMD_STATUS, 0x00])


@dataclass
class ProtocolStream:
    """A framed protocol stream ready for BLE transmission.

    Consists of a 9-byte header and a list of body chunks, each
    prefixed with a sequence number.
    """

    header: bytes
    body_chunks: list[bytes]


def frame_stream(body_data: bytes) -> ProtocolStream:
    """Wrap command bytes in the communication protocol stream.

    Header format (9 bytes):
      [0]   preamble  0xFF
      [1]   flags     0xF0
      [2:4] magic     0x12 0x34
      [4:8] length    body length as 4-byte little-endian
      [8]   checksum  sum of bytes [0:8] & 0xFF

    Body is split into 500-byte chunks. Each chunk is prefixed with a
    1-byte sequence number (skipping value 27 to avoid ESC collisions).
    The last chunk has the magic bytes appended.
    """
    length_bytes = len(body_data).to_bytes(4, "little")

    header_prefix = bytes([PREAMBLE, FLAGS]) + MAGIC + length_bytes
    checksum = sum(header_prefix) & 0xFF
    header = header_prefix + bytes([checksum])

    # Split body into chunks
    raw_chunks = [
        body_data[i : i + BODY_CHUNK_SIZE]
        for i in range(0, len(body_data), BODY_CHUNK_SIZE)
    ]

    body_chunks = []
    for idx, chunk in enumerate(raw_chunks):
        # Sequence number skips 27 (ESC)
        seq = idx if idx < 27 else idx + 1
        seq_byte = bytes([seq & 0xFF])

        chunk_data = bytearray(chunk)
        # Append magic to the last chunk
        if idx == len(raw_chunks) - 1:
            chunk_data.extend(MAGIC)

        body_chunks.append(seq_byte + bytes(chunk_data))

    return ProtocolStream(header=header, body_chunks=body_chunks)


def build_print_stream(
    print_data: bytes,
    width: int,
    copies: int = 1,
    cut: bool = True,
    label_height_padded: int = LABEL_HEIGHT_PADDED,
) -> ProtocolStream:
    """Build the complete print command stream.

    Assembles: StartJob + Copies + PrintData + FormFeed + Status + EndJob,
    then wraps in the communication protocol stream.

    The Genie (LetraTag Connect) app always uses FormFeed after print data.
    The Cut command is only used by the Avatar app variant.
    """
    parts = [
        build_start_job(),
        build_copies(copies),
        build_print_data(width, label_height_padded, print_data),
        build_form_feed(),
        build_status_request(),
        build_end_job(),
    ]
    body = b"".join(parts)
    return frame_stream(body)


def parse_notification(data: bytes | bytearray) -> int:
    """Parse a print reply notification, return the response code."""
    if len(data) < 3:
        return -1
    return data[2]


def parse_manufacturer_data(data: bytes | bytearray) -> dict:
    """Parse BLE advertisement manufacturer data.

    Returns a dict with printer status fields:
      revision, cassette_id, cassette_name, busy, battery_level,
      charging, tape_jam, cutter_jam, battery_low, battery_too_low
    """
    if len(data) < 3:
        return {}

    raw = bytes(data)
    revision = (raw[0] & 0xF0) >> 4
    cassette_id = raw[1] & 0x0F
    carbon_type = (raw[1] >> 4) & 1
    busy = bool((raw[1] >> 5) & 1)
    battery_level = (raw[2] >> 4) & 3
    charging = bool((raw[2] >> 6) & 1)
    tape_jam = bool(raw[2] & 0x01)
    cutter_jam = bool(raw[2] & 0x02)
    battery_too_low = bool(raw[2] & 0x04)
    battery_low = bool(raw[2] & 0x08)

    return {
        "revision": revision,
        "cassette_id": cassette_id,
        "cassette_name": TAPE_SIZES.get(cassette_id, "Unknown"),
        "carbon_type": carbon_type,
        "busy": busy,
        "battery_level": battery_level,
        "charging": charging,
        "tape_jam": tape_jam,
        "cutter_jam": cutter_jam,
        "battery_low": battery_low,
        "battery_too_low": battery_too_low,
    }


def parse_status_info(data: bytes | bytearray) -> dict:
    """Parse extended status info from a status read response.

    The response starts at offset 2 of the raw BLE data.
    """
    if len(data) < 32:
        return {}

    buf = data[2:]
    status_length = buf[0]
    print_status = buf[1]
    job_id = int.from_bytes(buf[2:6], "little")
    label_index = int.from_bytes(buf[6:8], "little")
    cutter_status = buf[8]
    main_bay_status = buf[9]
    sku_bytes = buf[10:22]
    sku = bytes(sku_bytes).decode("ascii", errors="replace").strip()
    error_code = int.from_bytes(buf[22:26], "little")
    label_count = int.from_bytes(buf[26:28], "little")
    eps_charging = buf[28] if len(buf) > 28 else 0
    battery_level = buf[29] if len(buf) > 29 else 0

    return {
        "status_length": status_length,
        "print_status": print_status,
        "job_id": job_id,
        "label_index": label_index,
        "cutter_status": cutter_status,
        "main_bay_status": main_bay_status,
        "sku": sku,
        "error_code": error_code,
        "label_count": label_count,
        "eps_charging": eps_charging,
        "battery_level": battery_level,
    }
