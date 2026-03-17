# DYMO LetraTag Home Assistant Integration

Custom Home Assistant integration for DYMO LetraTag 200B Bluetooth label printers.

Communicates directly over BLE using the protocol reverse-engineered from the
DYMO LetraTag Connect 2.1.0 Android application.

## Requirements

- Home Assistant 2026.2 or later
- Bluetooth adapter (built-in or USB)
- DYMO LetraTag 200B printer
- 12mm tape cassette

## Installation

Copy `custom_components/letratag/` to your Home Assistant `config/custom_components/` directory:

```
config/
  custom_components/
    letratag/
      __init__.py
      config_flow.py
      const.py
      manifest.json
      printer.py
      protocol.py
      render.py
      sensor.py
      services.yaml
      strings.json
      translations/
        en.json
```

Restart Home Assistant.

## Setup

The integration auto-discovers LetraTag printers via BLE advertisements.

1. Go to **Settings > Devices & Services**
2. The printer should appear as a discovered device
3. Click **Configure** and confirm

For manual setup: **Add Integration > DYMO LetraTag**, then enter the Bluetooth address.

## Sensors

| Sensor | Description |
|--------|-------------|
| Battery | Battery level (percentage) with charging and low battery attributes |
| Cassette | Installed tape cassette type (Empty, 6mm, 9mm, 12mm, 19mm, 24mm) |
| Status | Printer state: Ready, Busy, Tape jam, Cutter jam, Battery too low |

Sensor data comes from BLE advertisement manufacturer data (passive, no connection required).

## Services

### `letratag.print_label`

Print a text label.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | yes | | Text to print. Use `\n` for multi-line. |
| `copies` | int | no | 1 | Number of copies (1-255) |
| `cut` | bool | no | true | Cut tape after printing |
| `font_size` | int | no | auto | Font size in pixels (6-26) |
| `font_path` | string | no | system | Path to a custom .ttf font |

Example:
```yaml
service: letratag.print_label
data:
  text: "Hello World"
  copies: 2
  cut: true
```

### `letratag.print_image`

Print an image file.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `image_path` | string | yes | | Path to image file |
| `copies` | int | no | 1 | Number of copies (1-255) |
| `cut` | bool | no | true | Cut tape after printing |

The image is automatically resized to fit the tape height (26px for 12mm tape)
and converted to 1-bit monochrome.

## Text Rendering

Text is rendered directly at the printer's native resolution (26 pixels height
for 12mm tape) using Pillow TrueType font rendering. No screenshots, no line
doubling: pixel-perfect output at the hardware level.

Font selection priority:
1. Custom font via `font_path` parameter
2. DejaVu Sans Bold (system)
3. Liberation Sans Bold (system)
4. Noto Sans Bold (system)
5. Pillow default bitmap font (fallback)

Font size is auto-calculated to maximize the text height within the label area,
or can be set explicitly via the `font_size` parameter.

## BLE Protocol

The integration implements the full DYMO LetraTag BLE print protocol:

- **Service UUID**: `be3dd650-2b3d-42f1-99c1-f0f749dd0678`
- **Write characteristic**: `be3dd651-2b3d-42f1-99c1-f0f749dd0678`
- **Notify characteristic**: `be3dd652-2b3d-42f1-99c1-f0f749dd0678`

Print sequence: StartJob, SetCopies, PrintData (1bpp raster), Cut, Status, EndJob.

Data is framed with a 9-byte header (preamble, flags, magic, length, checksum)
and the body is split into 500-byte chunks with sequence numbers.

## License

MIT
