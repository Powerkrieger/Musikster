#!/usr/bin/env python3
# /// script
# dependencies = ["opencv-python-headless", "numpy", "potracer", "cairosvg"]
# ///
"""
Vectorizes a raster contour drawing (see make_contour.py) into smooth bezier
curves with potrace, instead of a jagged pixel-traced edge map. Run with
`uv run vectorize_contour.py`.

  uv run vectorize_contour.py [input_png] [output.svg]

Defaults to ../../contour.png -> ../../contour.svg. Also writes a PNG
preview next to the SVG (rasterized back at high resolution) so it's easy to
eyeball without opening a vector editor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cairosvg
import cv2
import numpy as np
import potrace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

BLACK_LEVEL = 128        # pixels darker than this count as ink
TURDSIZE = 2             # suppress speckles smaller than this many pixels
ALPHAMAX = 1.0           # corner smoothness (0 = all corners, 1.33 = very round)
OPTTOLERANCE = 0.2       # curve-fit tolerance — higher = fewer, smoother curve segments
STROKE_WIDTH = 1.4


def trace_to_svg(image_path: Path) -> tuple[str, int, int]:
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        sys.exit(f"Couldn't read {image_path}")
    height, width = img.shape

    # potrace.Bitmap.__init__ auto-inverts internally, so pass True=light here
    # to end up with True=ink after its invert().
    bitmap = potrace.Bitmap(img >= BLACK_LEVEL)
    path = bitmap.trace(turdsize=TURDSIZE, turnpolicy=4, alphamax=ALPHAMAX,
                         opticurve=True, opttolerance=OPTTOLERANCE)

    d_parts = []
    for curve in path:
        start = curve.start_point
        d = [f"M{start.x:.2f},{start.y:.2f}"]
        for seg in curve.segments:
            end = seg.end_point
            if seg.is_corner:
                c = seg.c
                d.append(f"L{c.x:.2f},{c.y:.2f} L{end.x:.2f},{end.y:.2f}")
            else:
                c1, c2 = seg.c1, seg.c2
                d.append(f"C{c1.x:.2f},{c1.y:.2f} {c2.x:.2f},{c2.y:.2f} {end.x:.2f},{end.y:.2f}")
        d.append("Z")
        d_parts.append(" ".join(d))

    path_data = " ".join(d_parts)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="white"/>'
        f'<path d="{path_data}" fill="black" fill-rule="evenodd"/>'
        f'</svg>'
    )
    return svg, width, height


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "contour.png"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "contour.svg"

    svg, width, height = trace_to_svg(input_path)
    output_path.write_text(svg)
    print(f"Wrote {output_path}")

    preview_path = output_path.with_suffix(".preview.png")
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(preview_path),
                      output_width=width * 2, output_height=height * 2)
    print(f"Wrote {preview_path}")


if __name__ == "__main__":
    main()
