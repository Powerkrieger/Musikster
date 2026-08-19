#!/usr/bin/env python3
# /// script
# dependencies = ["opencv-python-headless", "numpy"]
# ///
"""
Turns a photo into a single-line contour drawing (black lines on white),
instead of the harsher posterized/duotone look. Run with `uv run make_contour.py`.

  uv run make_contour.py [input_image] [output.png]

Defaults to ../photo.jpg -> ../contour.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

# Crop (left, top, right, bottom) in source-image pixels, applied before
# upscaling — trims background clutter that would otherwise show up as stray
# lines. Set to None to use the full image.
CROP_BOX = (0, 0, 165, 168)
UPSCALE = 3                 # smooths curve quality; the source photo is small
BILATERAL_D = 9             # edge-preserving smoothing before edge detection
BILATERAL_SIGMA = 50
CANNY_LOW = 40
CANNY_HIGH = 120


def make_contour(image_path: Path) -> np.ndarray:
    img = cv2.imread(str(image_path))
    if img is None:
        sys.exit(f"Couldn't read {image_path}")
    if CROP_BOX is not None:
        left, top, right, bottom = CROP_BOX
        img = img[top:bottom, left:right]

    h, w = img.shape[:2]
    img = cv2.resize(img, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    smooth = cv2.bilateralFilter(gray, d=BILATERAL_D, sigmaColor=BILATERAL_SIGMA, sigmaSpace=BILATERAL_SIGMA)
    edges = cv2.Canny(smooth, CANNY_LOW, CANNY_HIGH)
    return cv2.bitwise_not(edges)  # black lines on white


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "photo.jpg"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "contour.png"

    line_art = make_contour(input_path)
    cv2.imwrite(str(output_path), line_art)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
