"""Constants for the DYMO LetraTag integration."""

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
CMD_MEDIA_TYPE = ord("M")
CMD_PRINT_DENSITY = ord("C")
CMD_PRINT_DATA = ord("D")
CMD_FORM_FEED = ord("E")
CMD_STATUS = ord("A")
CMD_END = ord("Q")
CMD_COPIES = ord("#")
CMD_CUT = ord("p")

# Protocol framing
PREAMBLE = 0xFF
FLAGS = 0xF0
MAGIC = bytes([0x12, 0x34])
BODY_CHUNK_SIZE = 500

# Print data parameters
BPP_MONO = 0x81  # 1-bit monochrome
ALIGNMENT_CENTER = 0x02
DEFAULT_JOB_ID = bytes([0x9A, 0x02, 0x00, 0x00])

# Cut command values
CUT_TAPE = 48  # 0x30 = cut
NO_CUT = 49  # 0x31 = don't cut

# Label dimensions (12mm tape)
LABEL_HEIGHT = 26  # pixels
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

# Manufacturer data advertisement bit fields
ADV_BATTERY_TOO_LOW = 0x04
ADV_CUTTER_JAM = 0x02
ADV_TAPE_JAM = 0x01
ADV_BATTERY_LOW = 0x08

# Connection parameters
CONNECT_TIMEOUT = 15.0
DISCONNECT_TIMEOUT = 5.0

# Service names
SERVICE_PRINT_LABEL = "print_label"
SERVICE_PRINT_IMAGE = "print_image"

# Named fonts - display name -> list of candidate file paths
# Chosen for excellent readability at 26px native resolution
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
}


def resolve_font(name: str) -> str | None:
    """Resolve a font display name to its file path on this system."""
    from pathlib import Path

    candidates = FONT_MAP.get(name, [])
    for path in candidates:
        if Path(path).is_file():
            return path
    return None
