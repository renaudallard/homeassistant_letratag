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

"""Constants for the DYMO LetraTag integration."""

from pathlib import Path

DOMAIN = "letratag"

# BLE UUID templates - {UUID} replaced with device UUID (default "2b3d")
DEFAULT_DEVICE_UUID = "2b3d"
SERVICE_UUID = "be3dd650-{uuid}-42f1-99c1-f0f749dd0678"
PRINT_REQUEST_UUID = "be3dd651-{uuid}-42f1-99c1-f0f749dd0678"
PRINT_REPLY_UUID = "be3dd652-{uuid}-42f1-99c1-f0f749dd0678"
PRINT_SHORT_CMD_UUID = "be3dd653-{uuid}-42f1-99c1-f0f749dd0678"


def ble_uuid(template: str, device_uuid: str = DEFAULT_DEVICE_UUID) -> str:
    """Build a full BLE UUID from template and device UUID."""
    return template.format(uuid=device_uuid)


# ESC prefix for all print commands
ESC = 0x1B

# Command codes (ASCII character after ESC)
CMD_START = ord("s")
CMD_PRINT_DATA = ord("D")
CMD_FORM_FEED = ord("E")
CMD_STATUS = ord("A")
CMD_END = ord("Q")
CMD_COPIES = ord("#")

# Protocol framing
PREAMBLE = 0xFF
FLAGS = 0xF0
MAGIC = bytes([0x12, 0x34])
BODY_CHUNK_SIZE = 500

# Print data parameters
BPP_MONO = 0x81  # 1-bit monochrome
ALIGNMENT_CENTER = 0x02
DEFAULT_JOB_ID = bytes([0x9A, 0x02, 0x00, 0x00])

# Label dimensions (12mm tape)
LABEL_HEIGHT = 32  # pixels, matches the LetraTag Connect app print band
LABEL_HEIGHT_PADDED = 32  # bits (4 bytes per column)
MIN_RASTER_LENGTH = 150  # minimum rasterlines (columns) with padding

# Tape sizes by cassette ID
TAPE_SIZES = {
    0: "Empty",
    1: "6mm",
    2: "9mm",
    3: "12mm",
    4: "19mm",
    5: "24mm",
}

# Notification response codes
RESPONSE_SUCCESS = 0
RESPONSE_PRINTING = 1
RESPONSE_FAILED = 2
RESPONSE_SUCCESS_LOW_BATTERY = 3
RESPONSE_CANCELLED = 4
RESPONSE_FAILED_2 = 5
RESPONSE_FAILED_LOW_BATTERY = 6
RESPONSE_NO_CASSETTE = 7
RESPONSE_BAY_OPEN = 8
RESPONSE_CUTTER_JAM = 9

RESPONSE_MESSAGES = {
    RESPONSE_SUCCESS: "Print successful",
    RESPONSE_PRINTING: "Printing",
    RESPONSE_FAILED: "Print failed",
    RESPONSE_SUCCESS_LOW_BATTERY: "Print successful (low battery)",
    RESPONSE_CANCELLED: "Print cancelled",
    RESPONSE_FAILED_2: "Print failed",
    RESPONSE_FAILED_LOW_BATTERY: "Print failed (low battery)",
    RESPONSE_NO_CASSETTE: "No cassette",
    RESPONSE_BAY_OPEN: "Bay open",
    RESPONSE_CUTTER_JAM: "Cutter jam",
}

# Error codes from status info
ERROR_CODES = {
    0: "No error",
    1: "Power dip",
    2: "User abort",
    4: "API abort",
    8: "Communication error",
    16: "Underrun",
    64: "Label jam",
    128: "Cutter jam",
    256: "No cassette",
    512: "Bay open",
    1024: "Cutter blade stuck",
    2048: "Power too low",
}

# Service names
SERVICE_PRINT_LABEL = "print_label"
SERVICE_PRINT_IMAGE = "print_image"

# Fonts bundled with the integration (see fonts/ATTRIBUTION.md)
_BUNDLED_FONT_DIR = Path(__file__).parent / "fonts"


def _bundled(filename: str) -> str:
    """Absolute path to a font shipped inside the integration."""
    return str(_BUNDLED_FONT_DIR / filename)


# Named fonts - display name -> list of candidate file paths
# Chosen for excellent readability at 32px native resolution. System paths
# are tried first; bundled copies act as a fallback so the named fonts also
# work on hosts that do not ship them.
FONT_MAP = {
    "DejaVu Sans Bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    ],
    "DejaVu Mono Bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono-Bold.ttf",
    ],
    "DejaVu Serif Bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/dejavu-serif-fonts/DejaVuSerif-Bold.ttf",
    ],
    "Liberation Sans Bold": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
    ],
    "FreeSans Bold": [
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/gnu-free/FreeSansBold.ttf",
    ],
    "Roboto Bold": [
        "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf",
        _bundled("Roboto-Bold.ttf"),
    ],
    "Noto Serif Bold": [
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
        _bundled("NotoSerif-Bold.ttf"),
    ],
    "Courgette Bold": [
        _bundled("Courgette-Bold.ttf"),
    ],
    "Sancreek Bold": [
        _bundled("Sancreek-Bold.ttf"),
    ],
    "Noto Sans Bold": [
        _bundled("NotoSans-Bold.ttf"),
    ],
    "Open Sans Bold": [
        _bundled("OpenSans-Bold.ttf"),
    ],
    "Source Sans 3 Bold": [
        _bundled("SourceSans3-Bold.ttf"),
    ],
    "Inter Bold": [
        _bundled("Inter-Bold.ttf"),
    ],
    "Fira Sans Bold": [
        _bundled("FiraSans-Bold.ttf"),
    ],
    "Oswald Bold": [
        _bundled("Oswald-Bold.ttf"),
    ],
    "Archivo Narrow Bold": [
        _bundled("ArchivoNarrow-Bold.ttf"),
    ],
    "Bebas Neue": [
        _bundled("BebasNeue-Regular.ttf"),
    ],
    "Merriweather Bold": [
        _bundled("Merriweather-Bold.ttf"),
    ],
    "Roboto Slab Bold": [
        _bundled("RobotoSlab-Bold.ttf"),
    ],
    "JetBrains Mono Bold": [
        _bundled("JetBrainsMono-Bold.ttf"),
    ],
    "IBM Plex Mono Bold": [
        _bundled("IBMPlexMono-Bold.ttf"),
    ],
}


def resolve_font(name: str) -> str | None:
    """Resolve a font display name to its file path on this system."""
    candidates = FONT_MAP.get(name, [])
    for path in candidates:
        if Path(path).is_file():
            return path
    return None
