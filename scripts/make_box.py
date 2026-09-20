#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "fonttools", "shapely", "manifold3d", "scipy", "pillow"]
# ///
"""
Personalizes the card box: takes the PrusaSlicer project in ../3d/musikster_box.3mf
(box + sliding lid + coin recess, designed once by hand) and swaps the engraved
"Name / Musikster" label on the lid and the bottom for this person's, keeping
everything else — font, size, position, engraving depth — as in the template.
Run with `uv run make_box.py`.

  uv run make_box.py <slug> [output.3mf]

Defaults to ../people/<slug>/stl/musikster_box.3mf. Open that in PrusaSlicer and
slice as usual. The label text comes from people/<slug>/person.json "boxLabel"
(use \\n for the line break) and otherwise defaults to the German possessive,
"<name>s\\nMusikster" (or "<name>'\\nMusikster" for names that already end in an s
sound). A label wider than the template's is shrunk to fit the same face. A
preview PNG of both labels lands next to the 3MF, for a quick look before slicing.

How it works: PrusaSlicer bakes its text-tool volumes into plain triangle meshes,
so editing the text attribute alone would do nothing. Instead the script renders
the new text itself with the same font (Z003, the URW Zapf Chancery clone that
ships with ghostscript / fonts-urw-base35), extrudes it, and splices it into the
model in place of the old label meshes — after fitting its own rendering of the
*old* text against the old mesh to recover where the text sits and which way it
reads on each face.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
from shapely.affinity import affine_transform

from label3mf import (MODELS_DIR, PEOPLE_DIR, LabelFont, Project, Shape, Volume, center_at, draw_shape, escape,
                      extrude, find_font, load_person, outline_points, pretty, render_label, stack_images)

TEMPLATE_3MF = MODELS_DIR / "musikster_box.3mf"
FIT_TOLERANCE_MM = 0.25     # mean outline distance above which the template fit is considered broken

# The eight ways a 2D shape can be laid onto a face: 4 rotations x mirror.
ORIENTATIONS = [[1, 0, 0, 1], [0, -1, 1, 0], [-1, 0, 0, -1], [0, 1, -1, 0],
                [-1, 0, 0, 1], [0, 1, 1, 0], [1, 0, 0, -1], [0, -1, -1, 0]]


@dataclass
class Placement:
    """Where a label sits on its face, recovered from the template's baked mesh: the
    face's normal axis and depth interval, plus the 2D orientation that maps
    render_label() output onto the face's in-plane axes and the center to put it at."""
    normal_axis: int
    plane_axes: tuple[int, int]
    depth_lo: float
    depth_hi: float
    orientation: list[int]
    center: np.ndarray
    template_width: float
    template_bounds: tuple[float, float, float, float]

    def place(self, shape: Shape) -> Shape:
        """Oriented like the template's label and centered where it was."""
        return center_at(affine_transform(shape, self.orientation + [0, 0]), *self.center)

    def to_3d(self, shape: Shape, depth: float) -> tuple[np.ndarray, np.ndarray]:
        v2, f = extrude(self.place(shape), depth)
        v3 = np.zeros((len(v2), 3))
        v3[:, self.plane_axes[0]] = v2[:, 0]
        v3[:, self.plane_axes[1]] = v2[:, 1]
        v3[:, self.normal_axis] = self.depth_lo + v2[:, 2]
        return v3, f


def _face_outline_points(v: np.ndarray, f: np.ndarray, normal_axis: int, level: float,
                         spacing: float = 0.2) -> np.ndarray:
    """Points along the boundary of the extrusion's top face: its vertices plus samples
    along its boundary edges (the ones used by exactly one face triangle)."""
    on_face = np.all(np.abs(v[f][:, :, normal_axis] - level) < 1e-4, axis=1)
    edges = np.sort(f[on_face][:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    pts = [v]
    for a, b in uniq[counts == 1]:
        k = int(np.linalg.norm(v[b] - v[a]) / spacing)
        if k > 1:
            t = np.linspace(0, 1, k, endpoint=False)[1:, None]
            pts.append(v[a] + t * (v[b] - v[a]))
    pts = np.vstack(pts)
    return pts[np.abs(pts[:, normal_axis] - level) < 1e-4]


def fit_placement(font: LabelFont, project: Project, vol: Volume) -> Placement:
    """Render the template's own label and find the orientation under which it lands on
    the baked mesh. The baked mesh is an extrusion, so its outline is exactly the text's
    — compare outlines with nearest-neighbour distances."""
    v, f = project.sub_mesh(vol)
    extent = v.max(0) - v.min(0)
    n = int(np.argmin(extent))
    axes = tuple(i for i in range(3) if i != n)
    lo, hi = v[:, n].min(), v[:, n].max()
    baked = _face_outline_points(v, f, n, hi)[:, list(axes)]
    baked_tree = cKDTree(baked)
    baked_center = (baked.min(0) + baked.max(0)) / 2

    label = render_label(font, vol.text, vol.em_mm)
    best = None
    for orient in ORIENTATIONS:
        pts = outline_points(center_at(affine_transform(label, orient + [0, 0]), *baked_center))
        # Symmetric: every baked outline point should lie on the rendering and vice versa.
        score = max(cKDTree(pts).query(baked)[0].mean(), baked_tree.query(pts)[0].mean())
        if best is None or score < best[0]:
            best = (score, orient)
    score, orient = best
    if score > FIT_TOLERANCE_MM:
        sys.exit(f"Could not match the template's label mesh with a fresh rendering of {vol.text!r} "
                 f"(mean outline distance {score:.2f} mm). Font mismatch, or the template changed?")
    print(f"  fitted {vol.text!r}: orientation {orient}, center {np.round(baked_center, 2).tolist()}, "
          f"residual {score:.3f} mm")
    return Placement(n, axes, lo, hi, orient, baked_center, baked.max(0)[0] - baked.min(0)[0],
                     (*baked.min(0), *baked.max(0)))


def save_preview(panels: list[tuple[Placement, Shape]], out_path: Path, px_per_mm: float = 8) -> None:
    """The new labels as flat shapes, one panel per face, with the template label's
    extent drawn as a frame so you can see the new text stays within it."""
    pad = 4.0
    images = []
    for placement, shape in panels:
        x0, y0, x1, y1 = placement.template_bounds
        b = shape.bounds
        x0, y0, x1, y1 = min(x0, b[0]) - pad, min(y0, b[1]) - pad, max(x1, b[2]) + pad, max(y1, b[3]) + pad
        img = Image.new("RGB", (int((x1 - x0) * px_per_mm), int((y1 - y0) * px_per_mm)), "white")
        draw = ImageDraw.Draw(img)
        to_px = lambda x, y: ((x - x0) * px_per_mm, (y1 - y) * px_per_mm)   # y up, like the face
        tb = placement.template_bounds
        draw.rectangle([to_px(tb[0], tb[3]), to_px(tb[2], tb[1])], outline="#c8c8c8", width=2)
        draw_shape(draw, shape, to_px)
        images.append(img)
    stack_images(images).save(out_path)


def default_label(name: str) -> str:
    possessive = name + ("'" if name[-1:].lower() in ("s", "ß", "x", "z") else "s")
    return f"{possessive}\nMusikster"


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: uv run make_box.py <slug> [output.3mf]")
    slug = sys.argv[1]
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else PEOPLE_DIR / slug / "stl" / "musikster_box.3mf"
    person = load_person(slug)
    label = person.get("boxLabel") or default_label(person.get("name") or slug)
    font = find_font()
    project = Project(TEMPLATE_3MF)
    if not any(v.text is not None for v in project.volumes):
        sys.exit("The template has no text volumes to replace.")

    print(f"Label for {slug}: {label!r}")
    volumes, previews = [], []
    for vol in project.volumes:
        if vol.text is None:
            v, f = project.sub_mesh(vol)
            volumes.append((v, f, vol.xml))
            continue
        placement = fit_placement(font, project, vol)
        shape = render_label(font, label, vol.em_mm)
        b = shape.bounds
        width = b[2] - b[0]
        if width > placement.template_width + 0.01:
            scale = placement.template_width / width
            print(f"  {label!r} is {width:.1f} mm wide, template's was {placement.template_width:.1f} mm — "
                  f"shrinking to {scale:.0%}")
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2   # shrink about the center, so it stays put
            shape = affine_transform(shape, [scale, 0, 0, scale, cx * (1 - scale), cy * (1 - scale)])
        v, f = placement.to_3d(shape, vol.depth)
        previews.append((placement, placement.place(shape)))
        center = (v.min(0) + v.max(0)) / 2
        xml = vol.xml
        xml = re.sub(r'(<metadata type="volume" key="name" value=")[^"]*(")',
                     lambda m: m.group(1) + escape(label.replace("\n", " ")) + m.group(2), xml)
        xml = re.sub(r'(<slic3rpe:text [^>]*\btext=")[^"]*(")',
                     lambda m: m.group(1) + escape(label) + m.group(2), xml)
        for axis, key in enumerate(("source_offset_x", "source_offset_y", "source_offset_z")):
            xml = re.sub(rf'(key="{key}" value=")[^"]*(")', rf'\g<1>{center[axis]:.15g}\g<2>', xml)
        volumes.append((v, f, xml))

    project.write(output_path, volumes)
    print(f"Wrote {pretty(output_path)}")
    preview_path = output_path.with_name(output_path.stem + "_preview.png")
    save_preview(previews, preview_path)
    print(f"Wrote label preview: {pretty(preview_path)}")


if __name__ == "__main__":
    main()
