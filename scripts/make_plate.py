#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "fonttools", "shapely", "manifold3d", "scipy", "pillow"]
# ///
"""
Everything for one person on a single print plate, in three colours with two filament
swaps: the card box from make_box.py plus 32 tokens from `make_tokens.py --engrave-hand`,
laid out side by side in the box project (its printer and print settings, a Core One
with 0.15 mm layers), with the colour changes already set:

  colour 1  the first layer: the tokens' undersides around the engraved hand
  colour 2  from the second layer up to the top of the box's flat-lying lid — the hand
            shows in this colour through its lines, and it's the tokens' main colour
  colour 3  everything above the lid: the grip rails on it and the rest of the tray

  uv run make_plate.py <slug> [output.3mf]

Defaults to ../people/<slug>/stl/musikster_plate.3mf. Runs make_box.py and make_tokens.py
first (their outputs and previews land in people/<slug>/stl/ as usual; the token as
rock_on_coin_engraved.3mf), so the plate is always current. The swap heights depend on
the layer height, so keep the project's print profile, or move the lid swap by hand.
"""
from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from functools import reduce
from pathlib import Path

import numpy as np
from manifold3d import Manifold, Mesh

from label3mf import COLOR_CHANGES_ENTRY, PEOPLE_DIR, Project, color_changes_xml, pretty

SCRIPTS_DIR = Path(__file__).resolve().parent
TOKEN_COUNT = 32
MARGIN_MM = 5.0            # clearance to the bed edge
GAP_MM = 3.0               # between tokens, and between the tokens and the box
SECOND_COLOR = "#000000"   # what PrusaSlicer's preview shows for colours 2 and 3
THIRD_COLOR = "#E65100"


def run(*args: str) -> None:
    subprocess.run([sys.executable, str(SCRIPTS_DIR / args[0]), *args[1:]], check=True)


def volume_manifold(project: Project, vol) -> Manifold:
    v, f = project.sub_mesh(vol)
    return Manifold(Mesh(vert_properties=v.astype(np.float32), tri_verts=f.astype(np.uint32)))


def solid(project: Project) -> Manifold:
    """The object as printed: its parts, minus its negative volumes."""
    parts = [volume_manifold(project, v) for v in project.volumes if "NegativeVolume" not in v.xml]
    result = reduce(lambda a, b: a + b, parts)
    for v in project.volumes:
        if "NegativeVolume" in v.xml:
            result = result - volume_manifold(project, v)
    return result


def layer_tops(project: Project, up_to: float) -> list[float]:
    first = float(project.print_setting("first_layer_height"))
    height = float(project.print_setting("layer_height"))
    return [first + k * height for k in range(int((up_to - first) / height) + 2)]


def lid_swap_z(box: Project, box_solid: Manifold, bottom_z: float) -> float:
    """The top of the first layer that's above the lid. The lid lies flat with its label
    cut into the top face; the first layer that has nothing left over the label's
    footprint is the first one above the lid. (PrusaSlicer slices mid-layer, so that's
    where we look too.)"""
    label = next((v for v in box.volumes if v.text is not None
                  and np.argmin(np.ptp(box.sub_mesh(v)[0], axis=0)) == 2), None)
    if label is None:
        sys.exit("The box has no label lying flat — can't tell where the lid ends.")
    lv, _ = box.sub_mesh(label)
    lo, hi = lv.min(0), lv.max(0)
    over_label = box_solid ^ Manifold.cube([hi[0] - lo[0], hi[1] - lo[1], 1000]).translate([lo[0], lo[1], bottom_z])
    first = float(box.print_setting("first_layer_height"))
    height = float(box.print_setting("layer_height"))
    for top in layer_tops(box, 1000):
        mid = top - (first if top == first else height) / 2
        if mid > lo[2] - bottom_z and over_label.slice(bottom_z + mid).area() < 1.0:
            return top
    sys.exit("Couldn't find the top of the lid.")


def bed_bounds(project: Project) -> tuple[float, float, float, float]:
    pts = np.array([p.split("x") for p in project.print_setting("bed_shape").split(",")], dtype=float)
    return pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()


def translation(x: float, y: float, z: float) -> str:
    return f"1 0 0 0 1 0 0 0 1 {x:.9g} {y:.9g} {z:.9g}"


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: uv run make_plate.py <slug> [output.3mf]")
    slug = sys.argv[1]
    stl_dir = PEOPLE_DIR / slug / "stl"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else stl_dir / "musikster_plate.3mf"
    box_path, coin_path = stl_dir / "musikster_box.3mf", stl_dir / "rock_on_coin_engraved.3mf"
    run("make_box.py", slug, str(box_path))
    run("make_tokens.py", "--engrave-hand", slug, str(coin_path))
    box, coin = Project(box_path), Project(coin_path)
    print(f"Plate for {slug}:")

    # --- colour changes ---
    box_solid = solid(box)
    bx0, by0, bz0, bx1, by1, _ = box_solid.bounding_box()
    first = float(box.print_setting("first_layer_height"))
    lid_z = lid_swap_z(box, box_solid, bz0)
    changes = [(first + 0.01, SECOND_COLOR), (lid_z, THIRD_COLOR)]
    print(f"  colour changes (M600): after the first layer, and before the {lid_z:g} mm layer "
          f"(the first above the lid)")

    # --- layout: the box against the left edge, the tokens in a grid to its right ---
    ex0, ey0, ex1, ey1 = bed_bounds(box)
    cv, _ = coin.sub_mesh(max(coin.volumes, key=lambda v: np.ptp(coin.sub_mesh(v)[0][:, 0])))
    diameter = np.ptp(cv[:, 0])
    pitch = diameter + GAP_MM
    box_x = ex0 + MARGIN_MM - bx0
    box_y = (ey0 + ey1) / 2 - (by0 + by1) / 2
    region_x0, region_x1 = box_x + bx1 + GAP_MM, ex1 - MARGIN_MM
    region_y0, region_y1 = ey0 + MARGIN_MM, ey1 - MARGIN_MM
    cols = int((region_x1 - region_x0 + GAP_MM) // pitch)
    rows = -(-TOKEN_COUNT // cols) if cols else 0
    if cols == 0 or rows * pitch - GAP_MM > region_y1 - region_y0:
        sys.exit(f"{TOKEN_COUNT} tokens of Ø{diameter:.1f} mm don't fit next to the box on this bed.")
    x_start = (region_x0 + region_x1) / 2 - (cols * pitch - GAP_MM) / 2 + diameter / 2
    y_start = (region_y0 + region_y1) / 2 + (rows * pitch - GAP_MM) / 2 - diameter / 2
    coin_center = (cv.min(0) + cv.max(0)) / 2
    items = [f'  <item objectid="1" transform="{translation(box_x, box_y, -bz0)}" printable="1"/>\n']
    for i in range(TOKEN_COUNT):
        r, c = divmod(i, cols)
        items.append(f'  <item objectid="2" transform="'
                     f'{translation(x_start + c * pitch - coin_center[0], y_start - r * pitch - coin_center[1], -cv[:, 2].min())}'
                     f'" printable="1"/>\n')
    print(f"  box at the left, {TOKEN_COUNT} tokens in {rows} rows of {cols} to its right")

    # --- merge: the coin becomes object 2 of the box project, with TOKEN_COUNT instances ---
    coin_object = re.search(r'<object id="1" type="model">.*?</object>', coin.model_xml, re.S).group(0)
    coin_object = coin_object.replace('<object id="1"', '<object id="2"', 1)
    model_xml = box.model_xml.replace(" </resources>", f"  {coin_object}\n </resources>", 1)
    model_xml = re.sub(r"<build>.*?</build>", lambda m: "<build>\n" + "".join(items) + " </build>", model_xml, flags=re.S)
    coin_config = re.search(r'<object id="1" instances_count="1">.*?</object>', coin.config, re.S).group(0)
    coin_config = coin_config.replace('<object id="1" instances_count="1">',
                                      f'<object id="2" instances_count="{TOKEN_COUNT}">', 1)
    # The token template was made for an MMU; on the box's single-extruder printer it's all extruder 1.
    coin_config = re.sub(r'\s*<metadata type="(?:object|volume)" key="extruder" value="\d+"/>', "", coin_config)
    config = box.config.replace("</config>", f" {coin_config}\n</config>", 1)

    entries = dict(box.entries)
    entries["3D/3dmodel.model"] = model_xml.encode("utf-8")
    entries["Metadata/Slic3r_PE_model.config"] = config.encode("utf-8")
    entries[COLOR_CHANGES_ENTRY] = color_changes_xml(changes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    print(f"Wrote {pretty(output_path)}")


if __name__ == "__main__":
    main()
