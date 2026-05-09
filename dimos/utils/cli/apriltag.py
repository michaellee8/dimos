# Copyright 2025-2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Printable AprilTag PDF generator with calibration ruler.

Draws tag cells as vector rects (no rasterization) so the PDF prints crisply at any
DPI. The tag's outer black border edge measures `size_mm` — that's the value to pass
as `tag_size` to pose-estimation routines (pupil-apriltags, solvePnP, etc.).
"""

from __future__ import annotations

from pathlib import Path

import cv2
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

_FAMILIES = {
    "tag36h11": (cv2.aruco.DICT_APRILTAG_36h11, 586, 8),
    "tag25h9": (cv2.aruco.DICT_APRILTAG_25h9, 34, 7),
    "tag16h5": (cv2.aruco.DICT_APRILTAG_16h5, 29, 6),
}


def parse_id_spec(spec: str) -> list[int]:
    """Parse '0-49' or '0,1,5,10-20' into a sorted unique list of ints."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def _cell_matrix(family: str, tag_id: int) -> list[list[int]]:
    """Return the tag's NxN binary cell matrix (1=black, 0=white)."""
    dict_id, max_id, n = _FAMILIES[family]
    if tag_id < 0 or tag_id > max_id:
        raise ValueError(f"id {tag_id} out of range for {family} (0..{max_id})")
    aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
    bmp = cv2.aruco.generateImageMarker(aruco_dict, tag_id, n)
    return [[1 if bmp[r, c] == 0 else 0 for c in range(n)] for r in range(n)]


def _draw_tag(
    c: canvas.Canvas, family: str, tag_id: int, x0: float, y0: float, size: float
) -> None:
    """Draw the tag at (x0, y0) bottom-left with given side length, all in pt."""
    cells = _cell_matrix(family, tag_id)
    n = len(cells)
    cell = size / n
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    for r in range(n):
        for col in range(n):
            if cells[r][col]:
                # row 0 is the top of the tag in cv2 output; flip for reportlab y-up coords
                cy = y0 + (n - 1 - r) * cell
                cx = x0 + col * cell
                c.rect(cx, cy, cell, cell, stroke=0, fill=1)


def _draw_ruler(c: canvas.Canvas, page_w_pt: float, y_mm: float = 40.0) -> None:
    """Draw a 100 mm calibration ruler centered at y_mm above page bottom."""
    length_mm = 100.0
    x0 = (page_w_pt - length_mm * mm) / 2
    y0 = y_mm * mm
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    c.line(x0, y0, x0 + length_mm * mm, y0)
    for i in range(int(length_mm) // 10 + 1):
        x_tick = x0 + i * 10 * mm
        tick_h = (4 if i % 5 == 0 else 2) * mm
        c.line(x_tick, y0, x_tick, y0 + tick_h)
        if i % 5 == 0:
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0, 0, 0)
            c.drawCentredString(x_tick, y0 - 3 * mm, str(i * 10))
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        page_w_pt / 2,
        y0 + 10 * mm,
        "Calibration ruler — measure with caliper. Should be exactly 100 mm.",
    )


def generate_pdf(
    ids: list[int],
    out_path: Path,
    *,
    family: str = "tag36h11",
    size_mm: float = 100.0,
) -> Path:
    """Write a printable PDF: one AprilTag per A4 page with ID, size label, and ruler."""
    if family not in _FAMILIES:
        raise ValueError(f"unsupported family: {family}; choose from {sorted(_FAMILIES)}")
    if not ids:
        raise ValueError("no IDs to render")
    if size_mm <= 0 or size_mm > 180:
        raise ValueError(f"size_mm must be in (0, 180]; got {size_mm}")

    out_path = Path(out_path)
    page_w_pt, page_h_pt = A4
    c = canvas.Canvas(str(out_path), pagesize=A4)

    for tag_id in ids:
        x_tag = (page_w_pt - size_mm * mm) / 2
        y_tag = page_h_pt - (70 + size_mm) * mm
        _draw_tag(c, family, tag_id, x_tag, y_tag, size_mm * mm)

        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(page_w_pt / 2, page_h_pt - 30 * mm, f"{family}  —  ID {tag_id}")
        c.setFont("Helvetica", 10)
        c.drawCentredString(
            page_w_pt / 2,
            page_h_pt - 45 * mm,
            f"black border edge = {size_mm:g} mm  (use this as tag_size)",
        )
        c.setFont("Helvetica", 9)
        c.drawCentredString(
            page_w_pt / 2,
            y_tag - 10 * mm,
            "Print at 100% / Actual Size — DO NOT use 'Fit to Page'.",
        )
        _draw_ruler(c, page_w_pt)
        c.showPage()

    c.save()
    return out_path
