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

"""Text and image rendering for DYMO LetraTag labels.

Renders text directly to 1-bit raster data at the printer's native
resolution (26px height for 12mm tape) using Pillow TrueType rendering.
No screenshots, no line doubling: direct pixel-perfect output.

Raster format:
  - Each "rasterline" is one vertical column of the label.
  - Rasterlines are ordered left-to-right.
  - Within a rasterline, index 0 = top pixel, index N = bottom pixel.
  - Columns are packed into bytes using the printer's expected bit layout
    (swap 8-bit chunks, then pack MSB-first).

Banner mode (rotate=True):
  - Each character is rendered at full tape width, then characters are
    laid out sequentially along the tape.
  - The image is transposed so rows become rasterlines.
  - When the tape is turned 90 degrees, text reads normally.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .const import LABEL_HEIGHT, MIN_RASTER_LENGTH

_LOGGER = logging.getLogger(__name__)

# Font search paths, in priority order
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _find_system_font() -> str | None:
    """Find the first available system TrueType font."""
    for path in _FONT_PATHS:
        if Path(path).is_file():
            return path
    return None


def _load_font(
    font_path: str | None, font_size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font, falling back to system fonts."""
    if font_path and Path(font_path).is_file():
        return ImageFont.truetype(font_path, font_size)

    system_font = _find_system_font()
    if system_font:
        return ImageFont.truetype(system_font, font_size)

    _LOGGER.warning("No TrueType font found, using Pillow default bitmap font")
    return ImageFont.load_default()


def _auto_font_size(
    text: str,
    font_path: str | None,
    max_height: int,
) -> int:
    """Find the largest font size that fits within max_height pixels."""
    best = 8
    system_font = font_path or _find_system_font()
    if not system_font:
        return best

    for size in range(max_height, 6, -1):
        font = ImageFont.truetype(system_font, size)
        bbox = font.getbbox(text)
        text_height = bbox[3] - bbox[1]
        if text_height <= max_height:
            return size
    return best


def _auto_font_size_by_width(
    text: str,
    font_path: str | None,
    max_width: int,
) -> int:
    """Find the largest font size where text width fits within max_width."""
    best = 8
    system_font = font_path or _find_system_font()
    if not system_font:
        return best

    for size in range(max_width * 2, 6, -1):
        font = ImageFont.truetype(system_font, size)
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        if text_width <= max_width:
            return size
    return best


def render_text(
    text: str,
    label_height: int = LABEL_HEIGHT,
    font_path: str | None = None,
    font_size: int | None = None,
    max_width: int | None = None,
) -> Image.Image:
    """Render text to a 1-bit PIL Image at the printer's native resolution.

    Args:
        text: Text to render. Newlines split into multiple lines.
        label_height: Pixel height of the label (26 for 12mm tape).
        font_path: Optional path to a .ttf font file.
        font_size: Optional font size in pixels. Auto-calculated if None.
        max_width: Optional maximum width in pixels.

    Returns:
        A mode "1" PIL Image (1-bit, black on white).
    """
    lines = text.split("\n") if "\n" in text else [text]
    n_lines = len(lines)

    # Margin: 1px top and bottom
    available_height = label_height - 2
    line_height = available_height // n_lines

    if font_size is None:
        # Auto-size: find largest font that fits one line height
        sample = max(lines, key=len)
        font_size = _auto_font_size(sample, font_path, line_height)

    font = _load_font(font_path, font_size)

    # Measure total width needed
    widths = []
    for line in lines:
        bbox = font.getbbox(line)
        widths.append(bbox[2] - bbox[0])
    total_width = int(max(widths)) + 4  # 2px padding each side

    if max_width and total_width > max_width:
        total_width = max_width

    # Render to grayscale first for best anti-aliasing, then threshold
    img = Image.new("L", (total_width, label_height), 255)
    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = (total_width - text_w) // 2 - bbox[0]
        # Vertical centering within this line's slot
        slot_top = 1 + i * line_height
        y = slot_top + (line_height - text_h) // 2 - bbox[1]

        draw.text((x, y), line, fill=0, font=font)

    # Convert to 1-bit with threshold
    return img.point(lambda x: 0 if x < 128 else 255, "1")


def render_text_banner(
    text: str,
    label_height: int = LABEL_HEIGHT,
    font_path: str | None = None,
    font_size: int | None = None,
    spacing: int = 2,
) -> Image.Image:
    """Render text in banner mode (rotated 90 degrees for vertical reading).

    Each character is rendered at a size that fills the tape width,
    then characters are placed sequentially along the tape. The result
    is transposed so that turning the printed tape 90 degrees shows
    normally readable text.

    Args:
        text: Text to render.
        label_height: Tape width in pixels (26 for 12mm).
        font_path: Optional path to a .ttf font file.
        font_size: Explicit font size. Auto-sized to fill tape width if None.
        spacing: Pixels of gap between characters.

    Returns:
        A mode "1" PIL Image ready for rasterline conversion.
    """
    if not text or not text.strip():
        # Return a minimal blank label for empty text
        blank = Image.new("1", (MIN_RASTER_LENGTH, label_height), 1)
        return blank

    usable = label_height - 2  # 1px margin each side

    # Find the widest character to determine font size by measuring each
    if font_size is None:
        system_font = font_path or _find_system_font()
        if system_font:
            probe = ImageFont.truetype(system_font, usable)
            widest_w: float = 0
            widest_ch = "M"
            for ch in text:
                if ch == " ":
                    continue
                bbox = probe.getbbox(ch)
                w = bbox[2] - bbox[0]
                if w > widest_w:
                    widest_w = w
                    widest_ch = ch
            font_size = _auto_font_size_by_width(widest_ch, font_path, usable)
        else:
            font_size = 8

    font = _load_font(font_path, font_size)

    # Measure each character
    char_blocks: list[tuple[str, int, int]] = []
    for ch in text:
        if ch == " ":
            char_blocks.append((" ", 0, font_size // 2))
        else:
            bbox = font.getbbox(ch)
            ch_w = int(bbox[2] - bbox[0])
            ch_h = int(bbox[3] - bbox[1])
            char_blocks.append((ch, ch_w, ch_h))

    # Total height of the vertical layout (becomes tape length after transpose)
    total_len = sum(h for _, _, h in char_blocks) + spacing * max(0, len(text) - 1)

    # Build the image: label_height wide x total_len tall
    img = Image.new("L", (label_height, total_len), 255)
    draw = ImageDraw.Draw(img)

    y_cursor = 0
    for ch, ch_w, ch_h in char_blocks:
        if ch == " ":
            y_cursor += ch_h + spacing
            continue
        bbox = font.getbbox(ch)
        x = (label_height - ch_w) // 2 - bbox[0]
        y = y_cursor - bbox[1]
        draw.text((x, y), ch, fill=0, font=font)
        y_cursor += ch_h + spacing

    # Convert to 1-bit
    img = img.point(lambda x: 0 if x < 128 else 255, "1")

    # Transpose: swap width and height so rows become rasterlines.
    # This makes the label_height-wide image into a label_height-tall image,
    # ready for the standard rasterline column reader.
    return img.transpose(Image.Transpose.TRANSPOSE)


def image_to_rasterlines(
    img: Image.Image,
    label_height: int = LABEL_HEIGHT,
) -> list[list[int]]:
    """Convert a PIL Image to rasterlines (list of column bit-arrays).

    The image is resized to fit label_height if needed, converted to
    1-bit, then read column-by-column.

    Each rasterline is a list of ints (0 or 1) of length label_height,
    where 1 = black (print) and 0 = white (no print).
    """
    # Resize height to match label if needed, preserving aspect ratio
    if img.height != label_height:
        ratio = label_height / img.height
        new_width = max(1, int(img.width * ratio))
        img = img.resize((new_width, label_height), Image.Resampling.LANCZOS)

    # Convert to 1-bit
    if img.mode != "1":
        gray = img.convert("L")
        img = gray.point(lambda x: 0 if x < 128 else 255, "1")

    width, height = img.size
    px = img.load()
    if px is None:
        return []
    rasterlines = []

    for x in range(width):
        column = []
        for y in range(height):
            # In mode "1": 0 = black, 255 = white
            pixel = px[x, y]
            column.append(1 if pixel == 0 else 0)
        rasterlines.append(column)

    return rasterlines


def swap_bits(rasterlines: list[list[int]]) -> list[list[int]]:
    """Reverse the byte-level order within each rasterline.

    Matches the app's swapBits(): chunk each column into groups of 8,
    reverse the chunk order, flatten back.
    """
    result = []
    for column in rasterlines:
        chunks = [column[i : i + 8] for i in range(0, len(column), 8)]
        swapped = []
        for chunk in reversed(chunks):
            swapped.extend(chunk)
        result.append(swapped)
    return result


def adjust_padding(
    rasterlines: list[list[int]],
    column_height: int,
    min_length: int = MIN_RASTER_LENGTH,
) -> list[list[int]]:
    """Pad rasterlines to at least min_length columns.

    Alternates prepending and appending blank columns (all zeros).
    """
    padded = list(rasterlines)
    blank = [0] * column_height
    prepend = True
    while len(padded) < min_length:
        if prepend:
            padded.insert(0, blank)
        else:
            padded.append(blank)
        prepend = not prepend
    return padded


def rasterlines_to_bytes(rasterlines: list[list[int]]) -> bytes:
    """Convert rasterlines to printer byte data.

    Each rasterline (column) is chunked into 8-bit groups, and each
    group is converted to a byte with MSB-first bit ordering.
    """
    result = bytearray()
    for column in rasterlines:
        for i in range(0, len(column), 8):
            chunk = column[i : i + 8]
            byte_val = 0
            for bit in chunk:
                byte_val = (byte_val << 1) | bit
            result.append(byte_val)
    return bytes(result)


def prepare_print_data(
    img: Image.Image,
    label_height: int = LABEL_HEIGHT,
    min_raster_length: int = MIN_RASTER_LENGTH,
    max_width: int | None = None,
) -> tuple[int, bytes]:
    """Convert a PIL Image to print-ready data.

    Args:
        img: Input image (any mode, will be converted).
        label_height: Pixel height per column.
        min_raster_length: Minimum number of rasterlines (columns).
        max_width: Maximum rasterlines (columns). None for unlimited.

    Returns:
        (width, print_data) where width is the number of rasterlines
        and print_data is the packed byte data.
    """
    rasterlines = image_to_rasterlines(img, label_height)
    rasterlines = swap_bits(rasterlines)
    rasterlines = adjust_padding(rasterlines, label_height, min_raster_length)

    if max_width and len(rasterlines) > max_width:
        rasterlines = rasterlines[:max_width]

    width = len(rasterlines)
    print_data = rasterlines_to_bytes(rasterlines)
    return width, print_data


def render_and_prepare(
    text: str,
    label_height: int = LABEL_HEIGHT,
    font_path: str | None = None,
    font_size: int | None = None,
    max_width: int | None = None,
    rotate: bool = False,
) -> tuple[int, bytes]:
    """Render text and prepare print data in one step.

    Args:
        rotate: If True, render in banner mode (90 degree rotation).

    Returns:
        (width, print_data) ready for build_print_stream().
    """
    if rotate:
        img = render_text_banner(
            text,
            label_height=label_height,
            font_path=font_path,
            font_size=font_size,
        )
    else:
        img = render_text(
            text,
            label_height=label_height,
            font_path=font_path,
            font_size=font_size,
            max_width=max_width,
        )
    return prepare_print_data(img, label_height)
