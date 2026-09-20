#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "trimesh", "pillow", "manifold3d", "scipy", "networkx"]
# ///
"""
Engraves a height map into an existing coin STL via boolean subtraction,
instead of adding a bump-map relief on top. In the height map, 255 = "cut
here" and 0 = "leave the coin surface untouched" (see make_heightmap.py's
inverted output). Run with `uv run make_engraved_coin.py`.

  uv run make_engraved_coin.py <slug> [coin.stl] [heightmap.png] [output.stl]

Defaults to ../../people/<slug>/stl/coin.stl + ../../heightmap_inverted.png
-> ../../people/<slug>/stl/coin_engraved.stl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PEOPLE_DIR = REPO_ROOT / "people"

PORTRAIT_WIDTH_MM = 24.0   # inset within the coin face — must keep the rectangle's
                            # corners inside the coin's radius (see make_coin.py's note)
ENGRAVE_DEPTH_MM = 0.8      # how deep the cut regions go
SAFETY_MARGIN_MM = 1.0      # how far the cutter pokes above the coin face, for a clean boolean

BLANK_COIN_DIAMETER_MM = 40.0
BLANK_COIN_THICKNESS_MM = 3.0
FLAT_TOLERANCE_MM = 0.01


def build_cutter_mesh(levels: np.ndarray, width_mm: float, coin_top_z: float,
                       engrave_depth_mm: float, safety_margin_mm: float) -> trimesh.Trimesh:
    """A heightfield block with a FLAT top (poking above the coin surface) and a
    VARYING bottom — the mirror image of make_coin.py's relief block. Where
    levels=1 ("cut"), the bottom drops to coin_top_z - engrave_depth_mm, fully
    overlapping the coin there. Where levels=0 ("leave alone"), the bottom sits
    exactly at coin_top_z, touching the coin's solid volume only at a single
    surface with ~zero overlap, so subtracting removes nothing there.
    """
    rows, cols = levels.shape
    height_mm = width_mm * rows / cols
    xs = np.linspace(-width_mm / 2, width_mm / 2, cols)
    ys = np.linspace(height_mm / 2, -height_mm / 2, rows)
    X, Y = np.meshgrid(xs, ys)
    Z_bottom = coin_top_z - levels * engrave_depth_mm
    z_top = coin_top_z + safety_margin_mm

    bottom_verts = np.stack([X, Y, Z_bottom], axis=-1).reshape(-1, 3)
    top_verts = np.stack([X, Y, np.full_like(Z_bottom, z_top)], axis=-1).reshape(-1, 3)
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
        sys.exit("Usage: uv run make_engraved_coin.py <slug> [coin.stl] [heightmap.png] [output.stl]")
    slug = sys.argv[1]
    stl_dir = PEOPLE_DIR / slug / "stl"
    coin_path = Path(sys.argv[2]) if len(sys.argv) > 2 else stl_dir / "coin.stl"
    heightmap_path = Path(sys.argv[3]) if len(sys.argv) > 3 else REPO_ROOT / "heightmap_inverted.png"
    output_path = Path(sys.argv[4]) if len(sys.argv) > 4 else stl_dir / "coin_engraved.stl"
    output_path = output_path.resolve()

    if coin_path.exists():
        print(f"Loading coin {coin_path} …")
        coin = trimesh.load(coin_path)
    else:
        coin = None

    # Is nearly the whole top face at the same z (i.e. actually flat)?
    if coin is not None:
        near_top = coin.vertices[np.abs(coin.vertices[:, 2] - coin.bounds[1][2]) < FLAT_TOLERANCE_MM]
        top_area_ratio = len(near_top) / len(coin.vertices)
    else:
        top_area_ratio = 0.0

    if coin is None or top_area_ratio < 0.2:
        if coin is not None:
            print(f"  {coin_path.name} isn't flat on top (only {top_area_ratio:.0%} of vertices sit at "
                  f"the max height) — it already has an older relief baked in. Engraving into a fresh "
                  f"blank coin instead so the cut geometry is correct everywhere.")
        else:
            print(f"  {coin_path} not found — building a fresh blank coin.")
        coin = trimesh.creation.cylinder(radius=BLANK_COIN_DIAMETER_MM / 2,
                                          height=BLANK_COIN_THICKNESS_MM, sections=160)
        coin.apply_translation([0, 0, BLANK_COIN_THICKNESS_MM / 2])
        output_path = output_path.with_name(output_path.stem + "_blank" + output_path.suffix)

    coin_top_z = coin.bounds[1][2]
    diameter_mm = coin.bounds[1][0] - coin.bounds[0][0]
    print(f"  coin top z={coin_top_z:.2f}mm, diameter={diameter_mm:.1f}mm")

    half_diag = (PORTRAIT_WIDTH_MM ** 2 + (PORTRAIT_WIDTH_MM * 495 / 400) ** 2) ** 0.5 / 2
    if half_diag > diameter_mm / 2:
        sys.exit(f"PORTRAIT_WIDTH_MM={PORTRAIT_WIDTH_MM} is too big — its corners "
                  f"(radius {half_diag:.1f}mm) would poke outside the coin (radius {diameter_mm/2:.1f}mm).")

    print(f"Loading height map {heightmap_path} …")
    levels = np.asarray(Image.open(heightmap_path).convert("L"), dtype=np.float64) / 255.0

    print("Building cutter…")
    cutter = build_cutter_mesh(levels, PORTRAIT_WIDTH_MM, coin_top_z, ENGRAVE_DEPTH_MM, SAFETY_MARGIN_MM)
    print(f"  cutter watertight: {cutter.is_watertight}")

    print("Subtracting (boolean difference)…")
    engraved = trimesh.boolean.difference([coin, cutter], engine="manifold")
    print(f"  engraved watertight: {engraved.is_watertight}, volume: {engraved.volume:.1f}mm^3 "
          f"(coin was {coin.volume:.1f}mm^3)")

    engraved.export(output_path)
    print(f"Wrote {output_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
