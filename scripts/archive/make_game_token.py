#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "trimesh", "pillow", "manifold3d", "scipy", "networkx"]
# ///
"""
Builds one gameplay token: a flat circular disk with a letter embossed into
the face as a bas-relief, using the same heightfield-relief approach as
make_coin.py (just with a rasterized glyph instead of a photo). Print this
STL COIN_COUNT times in your slicer — the geometry is identical per token,
so there's no reason to duplicate the mesh in the file itself.

  uv run make_game_token.py [output.stl]

Defaults to ../../stl/game_token_A.stl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# --- physical parameters (mm) -----------------------------------------------
COIN_COUNT = 20                 # how many of these to print — geometry doesn't change with count
LETTER = "A"
COIN_DIAMETER_MM = 24.0
COIN_THICKNESS_MM = 3.0
RELIEF_DEPTH_MM = 0.6           # raised letter height — raised reads better than engraved at this size
RELIEF_INSET_RATIO = 0.62       # glyph block's side, as a fraction of the coin diameter — must
                                 # stay under 1/sqrt(2) (~0.707) or corners poke past the coin edge
EMBED_MM = 1.0                  # how far the relief block is sunk into the coin before the union
GRID_RES = 160                  # samples per side of the glyph grid
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def load_letter_heightfield(letter: str, grid_res: int) -> np.ndarray:
    """Rasterize a single bold glyph, centered, as a binary height mask (1.0 on
    the letter, 0.0 off it) at high supersampled resolution then downsize, so
    the edge anti-aliases into a smooth relief slope instead of a jagged step.
    """
    supersample = 4
    size = grid_res * supersample
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, size=int(size * 0.8))
    bbox = draw.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pos = ((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1])
    draw.text(pos, letter, fill=255, font=font)
    img = img.resize((grid_res, grid_res), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64) / 255.0


def build_relief_mesh(levels: np.ndarray, inset_size_mm: float, z_base: float,
                       relief_depth_mm: float, embed_mm: float) -> trimesh.Trimesh:
    """A heightfield block: a top surface following `levels`, a flat bottom sunk
    `embed_mm` below the coin face for a clean boolean union, and side walls
    stitching the two together into a closed solid. (Same construction as
    make_coin.py's build_relief_mesh — kept separate here since callers pass
    the levels array in slightly different shapes/units.)
    """
    n = levels.shape[0]
    xs = np.linspace(-inset_size_mm / 2, inset_size_mm / 2, n)
    ys = np.linspace(inset_size_mm / 2, -inset_size_mm / 2, n)
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
    gy, gx = np.gradient(levels.astype(np.float64))
    light = np.array([-0.5, 0.5, 1.0])
    light /= np.linalg.norm(light)
    normals = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    shade = np.clip(normals @ light, 0.05, 1.0)
    img = Image.fromarray((shade * 255).astype(np.uint8), mode="L").resize((400, 400), Image.LANCZOS)
    img.save(out_path)


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "stl" / "game_token_A.stl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Rasterizing letter {LETTER!r}…")
    levels = load_letter_heightfield(LETTER, GRID_RES)

    preview_path = output_path.with_name(output_path.stem + "_preview.png")
    save_preview(levels, preview_path)
    print(f"Wrote relief preview: {preview_path.relative_to(REPO_ROOT)}")

    print("Building token base…")
    coin = trimesh.creation.cylinder(radius=COIN_DIAMETER_MM / 2, height=COIN_THICKNESS_MM, sections=120)
    coin.apply_translation([0, 0, COIN_THICKNESS_MM / 2])

    print("Building letter relief…")
    inset_size_mm = COIN_DIAMETER_MM * RELIEF_INSET_RATIO
    relief = build_relief_mesh(levels, inset_size_mm, COIN_THICKNESS_MM, RELIEF_DEPTH_MM, EMBED_MM)

    print("Fusing (boolean union)…")
    combined = trimesh.boolean.union([coin, relief], engine="manifold")
    print(f"  combined watertight: {combined.is_watertight}, volume: {combined.volume:.1f} mm^3")

    combined.export(output_path)
    print(f"Wrote {output_path.relative_to(REPO_ROOT)}")
    print(f"Print this {COIN_COUNT}x in your slicer (arrange/array copies there) for a full set.")


if __name__ == "__main__":
    main()
