<p align="center">
  <img src="https://brands.home-assistant.io/_/bluetooth/dark_logo.png" width="64" alt="">
</p>

<h1 align="center">DYMO LetraTag for Home Assistant</h1>

<p align="center">
  <a href="https://github.com/homeassistant-letratag"><img src="https://img.shields.io/badge/home%20assistant-2026.2+-blue?style=flat-square&logo=homeassistant" alt="HA 2026.2+"></a>
  <a href="#"><img src="https://img.shields.io/badge/bluetooth-BLE-0082FC?style=flat-square&logo=bluetooth" alt="BLE"></a>
  <a href="#"><img src="https://img.shields.io/badge/protocol-reverse--engineered-orange?style=flat-square" alt="Reverse Engineered"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--2--Clause-green?style=flat-square" alt="BSD 2-Clause License"></a>
</p>

<p align="center">
  Custom Home Assistant integration for <strong>DYMO LetraTag 200B</strong> Bluetooth label printers.<br>
  BLE protocol fully reverse-engineered from the DYMO LetraTag Connect Android app.
</p>

---

## Features

- **BLE auto-discovery** - printers appear automatically in Home Assistant
- **Lovelace card** - responsive UI with live preview, font/size selectors, and banner mode toggle
- **Text label printing** - render and print text directly from service calls
- **Banner mode** - 90 degree rotated text for vertical/spine labels
- **Image label printing** - print any image file, auto-scaled to tape size
- **Native resolution rendering** - TrueType text rendered at 26px, pixel-perfect, no screenshots or line doubling
- **Live status sensors** - battery, cassette type, and printer state from passive BLE advertisements
- **5 built-in fonts** - DejaVu Sans, DejaVu Mono, DejaVu Serif, Liberation Sans, FreeSans (all Bold)
- **Multi-line support** - split text across lines with `\n`
- **Custom fonts** - use any TrueType font via path

---

## Requirements

| Component | Version |
|-----------|---------|
| Home Assistant | 2026.2+ |
| Python | 3.12+ |
| Bluetooth | BLE adapter (built-in or USB) |
| Hardware | DYMO LetraTag 200B |
| Tape | 12mm cassette |

---

## Installation

### Manual

Copy `custom_components/letratag/` into your Home Assistant configuration directory:

```
<config>/
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

### HACS

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz)

1. Open **HACS > Integrations**
2. Click the three dots menu (top right) > **Custom repositories**
3. Enter `https://github.com/renaudallard/homeassistant-letratag` and select category **Integration**
4. Click **Add**, then find **DYMO LetraTag** in the list and click **Download**
5. Restart Home Assistant

---

## Setup

The integration auto-discovers nearby LetraTag printers via BLE.

1. Go to **Settings > Devices & Services**
2. The printer appears as a discovered device
3. Click **Configure** and confirm

**Manual setup:** Add Integration > search **DYMO LetraTag** > enter the Bluetooth address.

---

## Lovelace Card

A custom card is included for printing labels directly from the UI.

### Adding the card

The card JS is automatically registered as a Lovelace resource when the integration loads (served securely via `StaticPathConfig` and auto-added to the resource collection). No manual resource configuration needed.

Just add a card to your dashboard:

```yaml
type: custom:letratag-card
title: Label Printer    # optional, defaults to "DYMO LetraTag"
```

The resource is automatically removed when the last LetraTag config entry is unloaded.

### Card features

- **Live label preview** - shows a tape-shaped preview that updates as you type
- **Text input** - multi-line textarea, Ctrl+Enter to print
- **Font selector** - 5 built-in fonts optimized for 26px resolution
- **Size slider** - set explicit pixel size or leave on Auto
- **Normal / Banner toggle** - switch between horizontal text and 90 degree banner mode
- **Copies and cut** - set copy count and tape cutting
- **Sensor display** - shows battery, cassette, and status from discovered sensors
- **Responsive** - adapts to any column width, stacks controls on narrow screens

---

## Sensors

Three sensors are created per printer, updated passively from BLE advertisement data (no active connection needed):

| Sensor | Type | Description |
|--------|------|-------------|
| **Battery** | `sensor` | Battery percentage (10/40/70/100%) with `charging`, `battery_low` attributes |
| **Cassette** | `sensor` | Tape type: Empty, 6mm, 9mm, 12mm, 19mm, 24mm |
| **Status** | `sensor` | Printer state: Ready, Busy, Tape jam, Cutter jam, Battery too low |

---

## Services

### `letratag.print_label`

Print a text label. Font size is auto-calculated to fill the tape height, or can be set explicitly.

| Parameter | Type | Required | Default | Description |
|-----------|------|:--------:|---------|-------------|
| `text` | string | **yes** | | Label text. Use `\n` for multiple lines |
| `copies` | int | no | `1` | Number of copies (1 - 255) |
| `cut` | bool | no | `true` | Cut tape after printing |
| `font_name` | string | no | | One of the 5 built-in fonts (see below) |
| `font_size` | int | no | auto | Font size in pixels (6 - 52) |
| `font_path` | string | no | | Path to a custom `.ttf` file (overrides `font_name`) |
| `rotate` | bool | no | `false` | Banner mode: rotate text 90 degrees |

```yaml
# Simple label
service: letratag.print_label
data:
  text: "Hello World"
```

```yaml
# Multi-line with font choice
service: letratag.print_label
data:
  text: "Kitchen\nShelf 3"
  copies: 2
  font_name: "DejaVu Mono Bold"
```

```yaml
# Banner label (rotated 90 degrees for vertical reading)
service: letratag.print_label
data:
  text: "OFFICE"
  rotate: true
```

### `letratag.print_image`

Print an image file. The image is automatically resized to the tape height and converted to 1-bit monochrome.

| Parameter | Type | Required | Default | Description |
|-----------|------|:--------:|---------|-------------|
| `image_path` | string | **yes** | | Path to image file (PNG, BMP, JPG, etc.) |
| `copies` | int | no | `1` | Number of copies (1 - 255) |
| `cut` | bool | no | `true` | Cut tape after printing |

```yaml
service: letratag.print_image
data:
  image_path: "/config/labels/qr_wifi.png"
  copies: 1
```

---

## Text Rendering

Text is rendered directly at the printer's native resolution using Pillow TrueType font rendering. No screenshots, no bitmap scaling, no line doubling.

**Built-in fonts** (selected for clarity at 26px):

| Name | Style | Best for |
|------|-------|----------|
| DejaVu Sans Bold | Sans-serif | General purpose, excellent hinting |
| DejaVu Mono Bold | Monospace | Serial numbers, codes, aligned text |
| DejaVu Serif Bold | Serif | Formal labels |
| Liberation Sans Bold | Sans-serif | Clean, compact |
| FreeSans Bold | Sans-serif | Wide language support |

If `font_name` is not specified, the system's first available DejaVu font is used.

### Banner Mode

When `rotate` is `true`, each character is rendered at full tape width and placed sequentially along the tape. The result is a label that reads normally when the tape is turned 90 degrees, ideal for:

- File folder spines
- Cable markers viewed from the side
- Vertical shelf labels
- Equipment panel labels

---

## BLE Protocol Reference

Protocol reverse-engineered from the DYMO LetraTag Connect 2.1.0 APK.

### UUIDs

| Role | UUID |
|------|------|
| Service | `be3dd650-2b3d-42f1-99c1-f0f749dd0678` |
| Write (print request) | `be3dd651-2b3d-42f1-99c1-f0f749dd0678` |
| Notify (print reply) | `be3dd652-2b3d-42f1-99c1-f0f749dd0678` |
| Short command | `be3dd653-2b3d-42f1-99c1-f0f749dd0678` |

### Commands

All commands are prefixed with `ESC` (`0x1B`):

| Command | Code | Bytes | Description |
|---------|------|:-----:|-------------|
| StartJob | `s` | 6 | Begin print job with 4-byte job ID |
| MediaType | `M` | 6 | Set cassette type |
| PrintDensity | `C` | - | Set print density |
| PrintData | `D` | 12+N | Raster data: bpp, alignment, width(4), height(4), pixels(N) |
| FormFeed | `E` | 2 | Form feed |
| Status | `A` | 2 | Request printer status |
| Copies | `#` | 3 | Set number of copies |
| Cut | `p` | 3 | Cut tape (`0x30`) or skip (`0x31`) |
| EndJob | `Q` | 2 | End print job |

### Print Sequence

```
StartJob -> Copies -> PrintData -> Cut -> Status -> EndJob
```

### Communication Framing

Commands are concatenated into a body, then wrapped:

**Header (9 bytes):**

```
[0]     0xFF        preamble
[1]     0xF0        flags
[2:4]   0x12 0x34   magic
[4:8]   uint32 LE   body length
[8]     uint8       checksum (sum of [0:8] & 0xFF)
```

**Body:** split into 500-byte chunks, each prefixed with a 1-byte sequence number (value 27 is skipped to avoid ESC collision). Magic bytes `0x12 0x34` are appended to the last chunk.

### Raster Format

- 1 bit per pixel (`bpp = 0x81`), monochrome
- Image is stored column-by-column (each rasterline = one vertical column)
- 26 pixels per column for 12mm tape, packed into 4 bytes (32 bits)
- Byte order within each column is reversed in 8-bit groups before packing

### Manufacturer Data (Advertisement)

| Byte | Bits | Field |
|:----:|------|-------|
| 0 | [7:4] | Hardware revision |
| 1 | [3:0] | Cassette ID (0=empty, 1=6mm, 2=9mm, 3=12mm, 4=19mm, 5=24mm) |
| 1 | [4] | Carbon type |
| 1 | [5] | Busy / locked |
| 2 | [0] | Tape jam |
| 2 | [1] | Cutter jam |
| 2 | [2] | Battery too low to print |
| 2 | [3] | Battery low |
| 2 | [5:4] | Battery level (0-3) |
| 2 | [6] | Charging indicator |

### Print Response Codes

| Code | Meaning |
|:----:|---------|
| 0 | Success |
| 1 | Printing / ready for next label |
| 2, 5 | Failed |
| 3 | Success, battery low |
| 4 | Cancelled |
| 6 | Failed, battery low |
| 7 | No cassette |
| 8 | Bay open |
| 9 | Cutter jam |

---

## License

BSD 2-Clause. See [LICENSE](LICENSE).
