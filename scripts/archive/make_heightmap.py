#!/usr/bin/env python3
# /// script
# dependencies = ["pillow", "numpy", "rembg[cpu]", "opencv-python-headless"]
# ///
"""
Builds a grayscale height map from the posterized contrast photo, with the
background removed (segmented from the plain color photo via rembg) so only
the portrait carries height — the background sits flat at 0. Run with
`uv run make_heightmap.py`.

  uv run make_heightmap.py [color_photo] [contrast_photo] [output.png]

Defaults to ../../photo.jpg + ../../photo-contrast.jpg -> ../../heightmap.png.
The first run downloads rembg's ~1GB segmentation model (cached afterwards).
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rembg import remove

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# photo-contrast.jpg is a 3-color posterization (black/red/white) plus JPEG
# ringing noise around the band edges — classifying to the nearest of these
# three reference colors (instead of taking raw grayscale luminance) recovers
# the original crisp flat bands instead of a blurry gradient.
REFERENCE_COLORS = np.array([[0, 0, 0], [255, 0, 0], [255, 255, 255]], dtype=np.float64)
LEVELS = np.array([1.0, 0.45, 0.0])  # black highest, white lowest — flipped from the first pass


def main() -> None:
    color_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "photo.jpg"
    contrast_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "photo-contrast.jpg"
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else REPO_ROOT / "heightmap.png"

    print(f"Segmenting foreground from {color_path} …")
    color = Image.open(color_path).convert("RGB")
    cutout = remove(color)
    mask = np.array(cutout)[..., 3].astype(np.float64) / 255.0

    contrast = Image.open(contrast_path).convert("RGB")
    if contrast.size != cutout.size:
        contrast = contrast.resize(cutout.size, Image.NEAREST)
    contrast_arr = np.array(contrast).astype(np.float64)

    dist = np.linalg.norm(contrast_arr[:, :, None, :] - REFERENCE_COLORS[None, None, :, :], axis=-1)
    labels = np.argmin(dist, axis=-1).astype(np.uint8)
    labels = cv2.medianBlur(labels, 3)  # drop isolated JPEG-ringing speckles, keep edges crisp
    levels = LEVELS[labels]

    heightmap = (levels * mask * 255).astype(np.uint8)
    Image.fromarray(heightmap, mode="L").save(output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
