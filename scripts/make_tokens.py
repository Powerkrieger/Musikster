#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "fonttools", "shapely", "manifold3d", "pillow"]
# ///
"""
Personalizes the game tokens: takes the coin in ../3d/rock_on_coin.3mf (a Ø25 x 2 mm
disc with the "rock on" hand in a second colour on its underside) and engraves the
person's initial into the top face as a negative volume, so every player's tokens are
telling apart from the next deck's. Run with `uv run make_tokens.py`.

  uv run make_tokens.py [--engrave-hand] <slug> [output.3mf]

--engrave-hand is for printers without a multi-material unit: the hand stops being a
colour modifier and is cut one layer deep into the underside instead, and the project gets
a colour change (M600) after that first layer. The first layer is the underside's face in
the first colour; the rest of the coin, including what shows through the hand's lines,
is the second.

Defaults to ../people/<slug>/stl/rock_on_coin.3mf. Open that in PrusaSlicer, add
instances until you have 32 (see ../3d/README.md), and slice. The letter comes from
people/<slug>/person.json "tokenLetter" and otherwise is the first letter of "name",
in the same Z003 face as the box label (see make_box.py for where to get the font).
A preview PNG of the coin face lands next to the 3MF.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.affinity import affine_transform

from label3mf import (COLOR_CHANGES_ENTRY, MODELS_DIR, PEOPLE_DIR, Project, Shape, center_at, color_changes_xml,
                      draw_shape, extrude, find_font, load_person, negative_volume_xml, pretty, render_label)

TEMPLATE_3MF = MODELS_DIR / "rock_on_coin.3mf"

# --- engraving (mm) -----------------------------------------------------------
LETTER_EM_MM = 20.0        # font size; Z003 capitals come out ~11-13 mm tall at this
ENGRAVE_DEPTH_MM = 0.6     # 3 layers at 0.2 mm — deep enough to read, shallow enough to stay crisp
MAX_RADIUS_MM = 10.0       # the letter is shrunk until it fits in this circle around the coin's center
CUT_MARGIN_MM = 0.5        # how far the cutter pokes out above the coin face, for a clean boolean
HAND_COLOR = "#000000"     # --engrave-hand: the colour PrusaSlicer shows after the swap in its preview


def letter_shape(font, letter: str) -> Shape:
    shape = center_at(render_label(font, letter, LETTER_EM_MM), 0.0, 0.0)
    radius = max(np.hypot(x, y) for poly in getattr(shape, "geoms", [shape]) for x, y in poly.exterior.coords)
    if radius > MAX_RADIUS_MM:
        scale = MAX_RADIUS_MM / radius
        print(f"  {letter!r} reaches {radius:.1f} mm from the center — shrinking to {scale:.0%}")
        shape = affine_transform(shape, [scale, 0, 0, scale, 0, 0])
    return shape


def engraved_hand(project: Project, hand, bottom_z: float, depth: float) -> tuple[np.ndarray, np.ndarray, str]:
    """The hand colour modifier, a straight prism through the coin's lower half, squashed
    into a negative volume `depth` deep that pokes out below the underside."""
    v, f = project.sub_mesh(hand)
    lo, hi = v[:, 2].min(), v[:, 2].max()
    v = v.copy()
    v[:, 2] = bottom_z - CUT_MARGIN_MM + (v[:, 2] - lo) / (hi - lo) * (depth + CUT_MARGIN_MM)
    return v, f, negative_volume_xml("engraved hand", v)


def save_preview(shape: Shape, coin_radius: float, out_path: Path, px_per_mm: float = 12) -> None:
    pad = 2.0
    size = int(2 * (coin_radius + pad) * px_per_mm)
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    to_px = lambda x, y: ((x + coin_radius + pad) * px_per_mm, (coin_radius + pad - y) * px_per_mm)
    draw.ellipse([to_px(-coin_radius, coin_radius), to_px(coin_radius, -coin_radius)], fill="#f2e6c8", outline="#a08040", width=3)
    draw_shape(draw, shape, to_px, fill="#7a5c20", background="#f2e6c8")
    img.save(out_path)


def main() -> None:
    args = sys.argv[1:]
    engrave_hand = "--engrave-hand" in args
    args = [a for a in args if a != "--engrave-hand"]
    if len(args) not in (1, 2):
        sys.exit("Usage: uv run make_tokens.py [--engrave-hand] <slug> [output.3mf]")
    slug = args[0]
    output_path = Path(args[1]) if len(args) > 1 else PEOPLE_DIR / slug / "stl" / "rock_on_coin.3mf"
    person = load_person(slug)
    letter = person.get("tokenLetter") or (person.get("name") or slug)[:1].upper()
    if len(letter) != 1 or letter.isspace():
        sys.exit(f"tokenLetter must be a single character, got {letter!r}.")
    font = find_font()
    project = Project(TEMPLATE_3MF)

    # The coin body is the volume with the largest footprint; its top face is where the
    # letter goes (the hand modifier occupies the underside).
    body = max(project.volumes, key=lambda vol: np.ptp(project.sub_mesh(vol)[0][:, 0]))
    bv, _ = project.sub_mesh(body)
    bottom_z, top_z = bv[:, 2].min(), bv[:, 2].max()
    coin_radius = np.ptp(bv[:, 0]) / 2
    print(f"Token letter for {slug}: {letter!r} (coin {body.name!r}, Ø{2 * coin_radius:.1f} mm, top at z={top_z:g})")

    shape = letter_shape(font, letter)
    v, f = extrude(shape, ENGRAVE_DEPTH_MM + CUT_MARGIN_MM)
    v[:, 2] += top_z - ENGRAVE_DEPTH_MM

    volumes = [(*project.sub_mesh(vol), vol.xml) for vol in project.volumes if vol is body or not engrave_hand]
    extra_entries = {}
    if engrave_hand:
        hand = next(vol for vol in project.volumes if vol is not body)
        first_layer = float(project.print_setting("first_layer_height"))
        volumes.append(engraved_hand(project, hand, bottom_z, first_layer))
        # The swap goes before the second layer. PrusaSlicer puts it before the first layer
        # whose top reaches print_z, so just above the first layer works for any layer height.
        extra_entries[COLOR_CHANGES_ENTRY] = color_changes_xml([(first_layer + 0.01, HAND_COLOR)])
    volumes.append((v, f, negative_volume_xml(f"initial {letter}", v)))
    project.write(output_path, volumes, extra_entries)
    print(f"Wrote {pretty(output_path)} — print it 32 times")
    if engrave_hand:
        print(f"  Hand engraved {first_layer:g} mm (one layer) into the underside; colour change (M600) "
              f"after the first layer. Slice with a single-extruder printer profile, or it's ignored.")
    preview_path = output_path.with_name(output_path.stem + "_preview.png")
    save_preview(shape, coin_radius, preview_path)
    print(f"Wrote preview: {pretty(preview_path)}")


if __name__ == "__main__":
    main()
