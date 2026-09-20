#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "trimesh", "manifold3d", "matplotlib"]
# ///
"""
Builds a two-part, matchbox-style card box: an open-top TRAY that holds the
full card stack, and an open-ended SLEEVE it slides into. The tray is sized
around the deck's cut card size (see build_deck.py's cell_w/cell_h) plus
headroom for future additions; the sleeve is sized around the tray plus a
sliding clearance, with a short "stop lip" so the tray always protrudes
enough to grab even when pushed all the way in.

  uv run make_card_box.py

Writes ../deck_output/card_tray.stl, ../deck_output/card_sleeve.stl, and a
top/side dimension-check preview PNG. Print the tray floor-down as is; print
the sleeve rotated 90° so the closed back face sits on the bed and the open
front faces up — otherwise its top wall is an unsupported bridge across the
full cavity width.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "deck_output"

# --- card stack (mm) ---------------------------------------------------------
# CARD_W/CARD_H mirror build_deck.py's cell_w/cell_h (182.3pt/198.5pt @ 72dpi).
CARD_W_MM = 64.3
CARD_H_MM = 70.0
CARD_COUNT = 120
CARD_THICKNESS_MM = 0.35        # ~250gsm cardstock
CAPACITY_HEADROOM_CARDS = 20    # design for CARD_COUNT + this many, for future additions
STACK_SLACK_MM = 4.0            # extra vertical room above the stack inside the tray

# --- fit (mm) -----------------------------------------------------------------
FOOTPRINT_CLEARANCE_MM = 1.5    # per side, between card footprint and tray inner wall
SLEEVE_CLEARANCE_MM = 0.4       # per side, between tray outer shell and sleeve inner cavity
STOP_LIP_MM = 8.0               # how much of the tray always protrudes from a closed sleeve

# --- print (mm) -----------------------------------------------------------------
WALL_MM = 2.0                   # tray/sleeve wall + floor thickness
SLEEVE_BACK_MM = 2.5            # sleeve's closed back-wall thickness
NOTCH_RADIUS_MM = 8.0           # thumb notch cut into the tray's (and sleeve's) front top edge
OVERSHOOT_MM = 6.0              # how far cavity cuts extend past a face, for a clean boolean


def hollow_box(outer: tuple[float, float, float], cavity: tuple[float, float, float],
               cavity_center: tuple[float, float, float]) -> trimesh.Trimesh:
    """Outer box centered at (0, 0, outer_z/2), sitting on the floor at z=0.
    Cavity box placed at cavity_center and subtracted — extend the cavity past
    whichever outer faces should be "open" so the boolean cuts cleanly through.
    """
    ob = trimesh.creation.box(extents=outer)
    ob.apply_translation([0, 0, outer[2] / 2])
    cb = trimesh.creation.box(extents=cavity)
    cb.apply_translation(cavity_center)
    return trimesh.boolean.difference([ob, cb], engine="manifold")


def notch(mesh: trimesh.Trimesh, x: float, y: float, z: float, radius: float) -> trimesh.Trimesh:
    """Subtract a cylinder lying along X, centered at (x, y, z) — carves a
    thumb-sized semicircular scoop out of whatever top edge it overlaps.
    """
    cyl = trimesh.creation.cylinder(radius=radius, height=radius * 3, sections=48)
    cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    cyl.apply_translation([x, y, z])
    return trimesh.boolean.difference([mesh, cyl], engine="manifold")


def build_tray() -> tuple[trimesh.Trimesh, dict]:
    stack_len = (CARD_COUNT + CAPACITY_HEADROOM_CARDS) * CARD_THICKNESS_MM

    inner_x = CARD_W_MM + 2 * FOOTPRINT_CLEARANCE_MM
    inner_y = CARD_H_MM + 2 * FOOTPRINT_CLEARANCE_MM   # slide axis
    inner_z = stack_len + STACK_SLACK_MM

    outer_x = inner_x + 2 * WALL_MM
    outer_y = inner_y + 2 * WALL_MM
    outer_z = inner_z + WALL_MM   # floor only — open top

    cavity_z_extent = inner_z + OVERSHOOT_MM
    tray = hollow_box(
        outer=(outer_x, outer_y, outer_z),
        cavity=(inner_x, inner_y, cavity_z_extent),
        cavity_center=(0, 0, WALL_MM + cavity_z_extent / 2),
    )
    # Thumb notch in the top edge of the front (+Y) wall — the end that always
    # protrudes from the sleeve — so fingers can pinch the stack even closed.
    tray = notch(tray, 0, outer_y, outer_z, NOTCH_RADIUS_MM)

    dims = dict(outer_x=outer_x, outer_y=outer_y, outer_z=outer_z,
                inner_x=inner_x, inner_y=inner_y, inner_z=inner_z, stack_len=stack_len)
    return tray, dims


def build_sleeve(tray_dims: dict) -> tuple[trimesh.Trimesh, dict]:
    inner_x = tray_dims["outer_x"] + 2 * SLEEVE_CLEARANCE_MM
    inner_z = tray_dims["outer_z"] + 2 * SLEEVE_CLEARANCE_MM

    outer_x = inner_x + 2 * WALL_MM
    outer_z = inner_z + 2 * WALL_MM

    cavity_y = tray_dims["outer_y"] - STOP_LIP_MM   # shorter than the tray on purpose (the lip)
    outer_y = SLEEVE_BACK_MM + cavity_y

    cavity_y_extent = cavity_y + OVERSHOOT_MM
    sleeve = hollow_box(
        outer=(outer_x, outer_y, outer_z),
        cavity=(inner_x, cavity_y_extent, inner_z),
        cavity_center=(0, SLEEVE_BACK_MM + cavity_y_extent / 2, outer_z / 2),
    )
    # Matching notch at the open front's top edge, so the lip's notch stays reachable.
    sleeve = notch(sleeve, 0, outer_y, outer_z, NOTCH_RADIUS_MM)

    dims = dict(outer_x=outer_x, outer_y=outer_y, outer_z=outer_z, cavity_y=cavity_y)
    return sleeve, dims


def save_preview(tray_dims: dict, sleeve_dims: dict, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, (ax_top, ax_side) = plt.subplots(1, 2, figsize=(9, 4.5))

    # Top view (X vs Y): sleeve outline + tray outline, both centered on X=0.
    ax_top.add_patch(Rectangle((-sleeve_dims["outer_x"] / 2, 0), sleeve_dims["outer_x"], sleeve_dims["outer_y"],
                                fill=False, edgecolor="tab:blue", linewidth=1.5, label="sleeve"))
    ax_top.add_patch(Rectangle((-tray_dims["outer_x"] / 2, 0), tray_dims["outer_x"], tray_dims["outer_y"],
                                fill=False, edgecolor="tab:orange", linewidth=1.5, linestyle="--", label="tray (out)"))
    ax_top.set_title("Top view (mm)")
    ax_top.set_xlim(-sleeve_dims["outer_x"], sleeve_dims["outer_x"])
    ax_top.set_ylim(-5, max(sleeve_dims["outer_y"], tray_dims["outer_y"]) + 5)
    ax_top.set_aspect("equal")
    ax_top.legend(fontsize=8, loc="upper right")

    # Side view (Y vs Z): sleeve cavity + tray inserted, showing the stop lip.
    ax_side.add_patch(Rectangle((0, 0), sleeve_dims["outer_y"], sleeve_dims["outer_z"],
                                 fill=False, edgecolor="tab:blue", linewidth=1.5, label="sleeve"))
    tray_y0 = sleeve_dims["outer_y"] - tray_dims["outer_y"]  # pushed fully in
    ax_side.add_patch(Rectangle((tray_y0, 0), tray_dims["outer_y"], tray_dims["outer_z"],
                                 fill=False, edgecolor="tab:orange", linewidth=1.5, linestyle="--", label="tray (in)"))
    ax_side.set_title("Side view, tray closed (mm)")
    ax_side.set_xlim(-5, tray_y0 + tray_dims["outer_y"] + 5)
    ax_side.set_ylim(-5, max(sleeve_dims["outer_z"], tray_dims["outer_z"]) + 5)
    ax_side.set_aspect("equal")
    ax_side.legend(fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Building tray…")
    tray, tray_dims = build_tray()
    print(f"  tray outer: {tray_dims['outer_x']:.1f} x {tray_dims['outer_y']:.1f} x {tray_dims['outer_z']:.1f} mm"
          f"  (holds up to {CARD_COUNT + CAPACITY_HEADROOM_CARDS} cards, stack {tray_dims['stack_len']:.1f}mm)")
    print(f"  watertight: {tray.is_watertight}")
    tray_path = OUT_DIR / "card_tray.stl"
    tray.export(tray_path)
    print(f"  wrote {tray_path.relative_to(REPO_ROOT)}")

    print("Building sleeve…")
    sleeve, sleeve_dims = build_sleeve(tray_dims)
    print(f"  sleeve outer: {sleeve_dims['outer_x']:.1f} x {sleeve_dims['outer_y']:.1f} x {sleeve_dims['outer_z']:.1f} mm")
    print(f"  watertight: {sleeve.is_watertight}")
    sleeve_path = OUT_DIR / "card_sleeve.stl"
    sleeve.export(sleeve_path)
    print(f"  wrote {sleeve_path.relative_to(REPO_ROOT)}")

    preview_path = OUT_DIR / "card_box_preview.png"
    save_preview(tray_dims, sleeve_dims, preview_path)
    print(f"  wrote {preview_path.relative_to(REPO_ROOT)}")

    print(f"\nWhen closed, the tray's front lip protrudes {STOP_LIP_MM:.0f}mm past the sleeve opening for grip.")
    print("Print the tray floor-down as exported. Print the sleeve rotated 90°"
          " (closed back face on the bed, open front facing up) to avoid bridging its top wall.")


if __name__ == "__main__":
    main()
