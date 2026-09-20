#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "trimesh", "pillow", "scipy", "networkx"]
# ///
"""
Turns a height map (see make_heightmap.py) into a thin 3D-printable relief
plaque: a flat rectangular base with the image embossed into its top face.
Background pixels (already 0 in the height map) just stay flush with the
base — no separate masking/union step needed. Run with `uv run make_plaque.py`.

  uv run make_plaque.py <slug> [heightmap.png] [output.stl]

Defaults to ../../heightmap.png -> ../../people/<slug>/stl/plaque.stl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PEOPLE_DIR = REPO_ROOT / "people"

# --- physical parameters (mm) -----------------------------------------------
PLAQUE_WIDTH_MM = 50.0     # the image's height is derived from its aspect ratio
BASE_THICKNESS_MM = 1.0    # flush "keep" floor — stays thin so it's easy to sit outside the coin
RELIEF_DEPTH_MM = 15.0     # tall spike on "cut" areas — pokes fully through a coin for a clean
                            # subtraction in your slicer, regardless of exact alignment
BLUR_RADIUS = 0.0          # the height map is now discrete flat bands — no smoothing, keep steps crisp


def load_heightfield(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L")
    img = img.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))
    return np.asarray(img, dtype=np.float64) / 255.0


def build_plaque_mesh(levels: np.ndarray, width_mm: float, base_thickness_mm: float,
                       relief_depth_mm: float) -> trimesh.Trimesh:
    rows, cols = levels.shape
    height_mm = width_mm * rows / cols

    xs = np.linspace(-width_mm / 2, width_mm / 2, cols)
    ys = np.linspace(height_mm / 2, -height_mm / 2, rows)  # row 0 (image top) -> +Y
    X, Y = np.meshgrid(xs, ys)
    Z_top = base_thickness_mm + levels * relief_depth_mm

    top_verts = np.stack([X, Y, Z_top], axis=-1).reshape(-1, 3)
    bottom_verts = np.stack([X, Y, np.zeros_like(Z_top)], axis=-1).reshape(-1, 3)
    vertices = np.vstack([top_verts, bottom_verts])
    n_top = rows * cols

    def idx_top(i, j):
        return i * cols + j

    def idx_bottom(i, j):
        return n_top + i * cols + j

    faces = []
    for base_idx in (idx_top, idx_bottom):
        i = np.arange(rows - 1)
        j = np.arange(cols - 1)
        ii, jj = np.meshgrid(i, j, indexing="ij")
        a = base_idx(ii, jj).ravel()
        b = base_idx(ii, jj + 1).ravel()
        c = base_idx(ii + 1, jj).ravel()
        d = base_idx(ii + 1, jj + 1).ravel()
        faces.append(np.stack([a, c, d], axis=1))
        faces.append(np.stack([a, d, b], axis=1))

    def wall(top_a, top_b, bot_a, bot_b):
        return [np.stack([top_a, bot_a, bot_b], axis=1), np.stack([top_a, bot_b, top_b], axis=1)]

    i = np.arange(rows - 1)
    j = np.arange(cols - 1)
    faces += wall(idx_top(i, 0), idx_top(i + 1, 0), idx_bottom(i, 0), idx_bottom(i + 1, 0))
    faces += wall(idx_top(i, cols - 1), idx_top(i + 1, cols - 1), idx_bottom(i, cols - 1), idx_bottom(i + 1, cols - 1))
    faces += wall(idx_top(0, j), idx_top(0, j + 1), idx_bottom(0, j), idx_bottom(0, j + 1))
    faces += wall(idx_top(rows - 1, j), idx_top(rows - 1, j + 1), idx_bottom(rows - 1, j), idx_bottom(rows - 1, j + 1))

    faces = np.vstack(faces)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: uv run make_plaque.py <slug> [heightmap.png] [output.stl]")
    slug = sys.argv[1]
    input_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "heightmap.png"
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else PEOPLE_DIR / slug / "stl" / "plaque.stl"
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading {input_path} …")
    levels = load_heightfield(input_path)

    print("Building plaque mesh…")
    mesh = build_plaque_mesh(levels, PLAQUE_WIDTH_MM, BASE_THICKNESS_MM, RELIEF_DEPTH_MM)
    print(f"  watertight: {mesh.is_watertight}, faces: {len(mesh.faces)}, volume: {mesh.volume:.1f} mm^3")

    mesh.export(output_path)
    print(f"Wrote {output_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
