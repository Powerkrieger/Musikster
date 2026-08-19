#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "trimesh", "pillow", "manifold3d", "scipy", "networkx"]
# ///
"""
Turns a photo into a 3D-printable coin/medallion: a flat circular base with the
photo embossed into the face as a bas-relief. Run with `uv run make_coin.py`.

  uv run make_coin.py [input_image] [output.stl]

Defaults to ../photo-contrast.jpg -> ../deck_output/coin.stl. Also writes
a quick shaded-relief preview PNG next to the STL so you can sanity-check the
result before slicing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- physical parameters (mm) -----------------------------------------------
COIN_DIAMETER_MM = 40.0
COIN_THICKNESS_MM = 3.0
RELIEF_DEPTH_MM = 1.4          # how far the highest highlight rises above the coin face
RELIEF_INSET_RATIO = 0.68      # portrait square's side, as a fraction of the coin diameter —
                                # must stay under 1/sqrt(2) (~0.707) or the square's corners
                                # poke out past the coin's circular edge
EMBED_MM = 1.0                 # how far the relief block is sunk into the coin before the union
FEATHER_PX = 3                 # soft falloff at the portrait's circular edge, in source pixels
GRID_RES = 180                 # samples per side of the portrait grid


def load_heightfield(image_path: Path, grid_res: int, feather_px: float) -> np.ndarray:
    """Grayscale, center-crop to square, resize to the mesh grid, and fade to 0
    (flush with the coin face) outside an inscribed circle, so the photo reads
    as a round portrait rather than a square block.
    """
    img = Image.open(image_path).convert("L")
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((grid_res, grid_res), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    levels = np.asarray(img, dtype=np.float64) / 255.0

    yy, xx = np.mgrid[0:grid_res, 0:grid_res]
    center = (grid_res - 1) / 2
    dist = np.sqrt((xx - center) ** 2 + (yy - center) ** 2)
    radius = grid_res / 2
    circular_mask = np.clip((radius - dist) / feather_px, 0.0, 1.0)
    return levels * circular_mask


def build_relief_mesh(levels: np.ndarray, inset_size_mm: float, z_base: float,
                       relief_depth_mm: float, embed_mm: float) -> trimesh.Trimesh:
    """A heightfield block: a top surface following `levels` (image row 0 = +Y,
    i.e. the top of the photo lands at the top of the coin), a flat bottom
    sunk `embed_mm` below the coin face for a clean boolean union, and side
    walls stitching the two together into a closed solid.
    """
    n = levels.shape[0]
    xs = np.linspace(-inset_size_mm / 2, inset_size_mm / 2, n)
    ys = np.linspace(inset_size_mm / 2, -inset_size_mm / 2, n)  # row 0 -> +Y (image top)
    X, Y = np.meshgrid(xs, ys)
    Z_top = z_base + levels * relief_depth_mm
    z_bottom = z_base - embed_mm

    top_verts = np.stack([X, Y, Z_top], axis=-1).reshape(-1, 3)
    bottom_verts = np.stack([X, Y, np.full_like(Z_top, z_bottom)], axis=-1).reshape(-1, 3)
    vertices = np.vstack([top_verts, bottom_verts])
    n_top = n * n

    def idx_top(i, j):
        return i * n + j

    def idx_bottom(i, j):
        return n_top + i * n + j

    faces = []

    # Top + bottom grid surfaces (two triangles per cell).
    for base_idx in (idx_top, idx_bottom):
        i = np.arange(n - 1)
        j = np.arange(n - 1)
        ii, jj = np.meshgrid(i, j, indexing="ij")
        a = base_idx(ii, jj).ravel()
        b = base_idx(ii, jj + 1).ravel()
        c = base_idx(ii + 1, jj).ravel()
        d = base_idx(ii + 1, jj + 1).ravel()
        faces.append(np.stack([a, c, d], axis=1))
        faces.append(np.stack([a, d, b], axis=1))

    # Side walls around the four edges of the square grid.
    def wall(top_a, top_b, bot_a, bot_b):
        return [np.stack([top_a, bot_a, bot_b], axis=1), np.stack([top_a, bot_b, top_b], axis=1)]

    i = np.arange(n - 1)
    faces += wall(idx_top(i, 0), idx_top(i + 1, 0), idx_bottom(i, 0), idx_bottom(i + 1, 0))
    faces += wall(idx_top(i, n - 1), idx_top(i + 1, n - 1), idx_bottom(i, n - 1), idx_bottom(i + 1, n - 1))
    faces += wall(idx_top(0, i), idx_top(0, i + 1), idx_bottom(0, i), idx_bottom(0, i + 1))
    faces += wall(idx_top(n - 1, i), idx_top(n - 1, i + 1), idx_bottom(n - 1, i), idx_bottom(n - 1, i + 1))

    faces = np.vstack(faces)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def save_preview(levels: np.ndarray, out_path: Path) -> None:
    """A quick shaded-relief render of the height array, just to sanity-check
    the portrait before slicing — not part of the STL.
    """
    gy, gx = np.gradient(levels.astype(np.float64))
    light = np.array([-0.5, 0.5, 1.0])
    light /= np.linalg.norm(light)
    normals = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    shade = np.clip(normals @ light, 0.05, 1.0)
    img = Image.fromarray((shade * 255).astype(np.uint8), mode="L").resize((600, 600), Image.LANCZOS)
    img.save(out_path)


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "photo-contrast.jpg"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "deck_output" / "coin.stl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading {input_path} …")
    levels = load_heightfield(input_path, GRID_RES, FEATHER_PX)

    preview_path = output_path.with_name(output_path.stem + "_preview.png")
    save_preview(levels, preview_path)
    print(f"Wrote relief preview: {preview_path.relative_to(REPO_ROOT)}")

    print("Building coin base…")
    coin = trimesh.creation.cylinder(radius=COIN_DIAMETER_MM / 2, height=COIN_THICKNESS_MM, sections=160)
    coin.apply_translation([0, 0, COIN_THICKNESS_MM / 2])

    print("Building portrait relief…")
    inset_size_mm = COIN_DIAMETER_MM * RELIEF_INSET_RATIO
    relief = build_relief_mesh(levels, inset_size_mm, COIN_THICKNESS_MM, RELIEF_DEPTH_MM, EMBED_MM)
    print(f"  relief mesh watertight: {relief.is_watertight}")

    print("Fusing (boolean union)…")
    combined = trimesh.boolean.union([coin, relief], engine="manifold")
    print(f"  combined watertight: {combined.is_watertight}, volume: {combined.volume:.1f} mm^3")

    combined.export(output_path)
    print(f"Wrote {output_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
