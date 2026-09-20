"""
Shared plumbing for make_box.py and make_tokens.py: rendering text in the label font
(Z003) as flat shapes, extruding those into meshes, and reading/writing the meshes of a
PrusaSlicer 3MF project (its 3D/3dmodel.model plus Metadata/Slic3r_PE_model.config, which
splits the one big triangle list into named volumes). Not a script — the two scripts
declare the dependencies for this in their headers.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from manifold3d import CrossSection, FillRule
from shapely.affinity import affine_transform, translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parent.parent
PEOPLE_DIR = REPO_ROOT / "people"
MODELS_DIR = REPO_ROOT / "3d"

# The face PrusaSlicer's text tool used for the box label (it records the face name in the
# 3MF; the size is the "line_height" attribute, mm per em). Same font for the tokens.
FONT_CANDIDATES = [
    Path("/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf"),
    Path("/usr/share/fonts/urw-base35/Z003-MediumItalic.otf"),
    Path("/usr/share/fonts/X11/Type1/Z003-MediumItalic.pfb"),
]
LINE_PITCH_EM = 1.2         # baseline-to-baseline distance in ems (PrusaSlicer: ascent - descent + lineGap)
CURVE_STEPS = 10            # line segments per Bézier when flattening glyph outlines

Shape = Polygon | MultiPolygon


def load_person(slug: str) -> dict:
    config_path = PEOPLE_DIR / slug / "person.json"
    if not config_path.exists():
        available = sorted(p.parent.name for p in PEOPLE_DIR.glob("*/person.json"))
        sys.exit(f"No people/{slug}/person.json. Known people: {', '.join(available) or '(none)'}.")
    return json.loads(config_path.read_text(encoding="utf-8"))


def pretty(path: Path) -> Path:
    path = path.resolve()
    return path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path


# --- text -> 2D outline -------------------------------------------------------

class LabelFont:
    def __init__(self, path: Path):
        self.font = TTFont(path)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upem = self.font["head"].unitsPerEm

    def glyph(self, ch: str) -> tuple[Shape | None, float]:
        """One glyph as a filled shape in font units, plus its advance width."""
        name = self.cmap.get(ord(ch))
        if name is None:
            sys.exit(f"The label font has no glyph for {ch!r}.")
        g = self.glyphs[name]
        pen = RecordingPen()
        g.draw(pen)
        rings = [r for r in _flatten(pen.value) if len(r) >= 3]
        polys = [(Polygon(r), Polygon(r).exterior.is_ccw) for r in rings]
        polys = [(p.buffer(0), ccw) for p, ccw in polys if p.area > 0]
        if not polys:
            return None, g.width
        # Nonzero winding, near enough: contours wound like the largest one are outers,
        # the rest cut holes (the counters of 'e', 'A', ...).
        outer_ccw = max(polys, key=lambda pc: pc[0].area)[1]
        outer = unary_union([p for p, ccw in polys if ccw == outer_ccw])
        holes = unary_union([p for p, ccw in polys if ccw != outer_ccw])
        return outer.difference(holes), g.width


def find_font() -> LabelFont:
    for p in FONT_CANDIDATES:
        if p.exists():
            return LabelFont(p)
    sys.exit("Z003 (URW Zapf Chancery) not found — install fonts-urw-base35 (Debian/Ubuntu) or ghostscript's fonts.")


def _flatten(ops, steps: int = CURVE_STEPS) -> list[list[tuple[float, float]]]:
    """RecordingPen ops -> closed point rings, with Béziers turned into polylines."""
    rings: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    pt = (0.0, 0.0)
    ts = np.linspace(0.0, 1.0, steps + 1)[1:]
    for op, args in ops:
        if op == "moveTo":
            if cur:
                rings.append(cur)
            cur = [args[0]]
            pt = args[0]
        elif op == "lineTo":
            cur.append(args[0])
            pt = args[0]
        elif op == "curveTo":
            p0, p1, p2, p3 = np.array(pt), *map(np.array, args)
            for t in ts:
                cur.append(tuple((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3))
            pt = args[-1]
        elif op == "qCurveTo":
            # TrueType-style: implied on-curve points between consecutive off-curve ones.
            pts = list(map(np.array, args))
            p0 = np.array(pt)
            for i, c in enumerate(pts[:-1]):
                e = pts[i + 1] if i + 1 == len(pts) - 1 else (c + pts[i + 1]) / 2
                for t in ts:
                    cur.append(tuple((1 - t) ** 2 * p0 + 2 * (1 - t) * t * c + t * t * e))
                p0 = e
            pt = args[-1]
        elif op in ("closePath", "endPath"):
            if cur:
                rings.append(cur)
            cur = []
    if cur:
        rings.append(cur)
    return rings


def render_label(font: LabelFont, text: str, em_mm: float) -> Shape:
    """Lines centered on each other, first baseline at y=0, later lines below;
    x centered on the widest line. Same layout PrusaSlicer's text tool uses."""
    s = em_mm / font.upem
    pitch = LINE_PITCH_EM * em_mm
    shapes = []
    for li, line in enumerate(text.split("\n")):
        x = 0.0
        parts = []
        for ch in line:
            poly, adv = font.glyph(ch)
            if poly is not None and not poly.is_empty:
                parts.append(affine_transform(poly, [s, 0, 0, s, x, -li * pitch]))
            x += adv * s
        shapes += [translate(p, -x / 2, 0) for p in parts]
    return unary_union(shapes)


def center_at(shape: Shape, cx: float, cy: float) -> Shape:
    b = shape.bounds
    return translate(shape, cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2)


def outline_points(shape: Shape, spacing: float = 0.2) -> np.ndarray:
    pts = []
    for poly in (shape.geoms if isinstance(shape, MultiPolygon) else [shape]):
        for ring in [poly.exterior, *poly.interiors]:
            n = max(8, int(ring.length / spacing))
            pts += [ring.interpolate(d).coords[0] for d in np.linspace(0, ring.length, n, endpoint=False)]
    return np.array(pts)


def extrude(shape: Shape, depth: float) -> tuple[np.ndarray, np.ndarray]:
    """Shape in the XY plane -> (vertices, faces) of a z in [0, depth] solid."""
    rings = []
    for poly in (shape.geoms if isinstance(shape, MultiPolygon) else [shape]):
        rings.append(np.array(poly.exterior.coords[:-1], dtype=np.float64))
        rings += [np.array(h.coords[:-1], dtype=np.float64) for h in poly.interiors]
    mesh = CrossSection(rings, FillRule.EvenOdd).extrude(depth).to_mesh()
    return np.array(mesh.vert_properties)[:, :3], np.array(mesh.tri_verts)


def draw_shape(draw: ImageDraw.ImageDraw, shape: Shape, to_px, fill="#202020", background="white") -> None:
    """A filled 2D shape on a PIL canvas; to_px maps (x, y) in mm to pixels."""
    for poly in (shape.geoms if isinstance(shape, MultiPolygon) else [shape]):
        draw.polygon([to_px(*c) for c in poly.exterior.coords], fill=fill)
        for hole in poly.interiors:
            draw.polygon([to_px(*c) for c in hole.coords], fill=background)


def stack_images(images: list[Image.Image], gap: int = 20) -> Image.Image:
    w, h = max(i.width for i in images), sum(i.height for i in images) + gap * (len(images) - 1)
    sheet = Image.new("RGB", (w, h), "#e0e0e0")
    y = 0
    for img in images:
        sheet.paste(img, (0, y))
        y += img.height + gap
    return sheet


# --- the 3MF ------------------------------------------------------------------

@dataclass
class Volume:
    """One <volume> of PrusaSlicer's Slic3r_PE_model.config: a triangle range plus its xml."""
    xml: str
    first: int
    last: int

    @property
    def name(self) -> str:
        return unescape(re.search(r'<metadata type="volume" key="name" value="([^"]*)"', self.xml).group(1))

    @property
    def text(self) -> str | None:
        m = re.search(r'<slic3rpe:text [^>]*\btext="([^"]*)"', self.xml)
        return unescape(m.group(1)) if m else None

    @property
    def depth(self) -> float:
        return float(re.search(r'<slic3rpe:shape [^>]*\bdepth="([^"]+)"', self.xml).group(1))

    @property
    def em_mm(self) -> float:
        return float(re.search(r'\bline_height="([^"]+)"', self.xml).group(1))


def unescape(s: str) -> str:
    return s.replace("&#xA;", "\n").replace("&#10;", "\n").replace("&quot;", '"').replace("&apos;", "'") \
            .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("\n", "&#xA;")


class Project:
    """A PrusaSlicer 3MF with a single object, as mesh arrays plus its volume table."""

    def __init__(self, path: Path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.entries = {info.filename: z.read(info.filename) for info in z.infolist()}
        self.model_xml = self.entries["3D/3dmodel.model"].decode("utf-8")
        self.config = self.entries["Metadata/Slic3r_PE_model.config"].decode("utf-8")
        if len(re.findall(r"<object ", self.model_xml)) != 1:
            sys.exit(f"{pretty(path)}: expected exactly one object.")
        self.verts = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', self.model_xml), dtype=np.float64)
        self.tris = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', self.model_xml), dtype=np.int64)
        self.volumes = [Volume(m.group(0), int(m.group(1)), int(m.group(2)))
                        for m in re.finditer(r'<volume firstid="(\d+)" lastid="(\d+)">.*?</volume>', self.config, re.S)]
        if self.volumes[-1].last != len(self.tris) - 1 or \
                any(b.first != a.last + 1 for a, b in zip(self.volumes, self.volumes[1:])):
            sys.exit(f"{pretty(path)}: volumes don't tile the triangle list — not a layout this script understands.")

    def sub_mesh(self, vol: Volume) -> tuple[np.ndarray, np.ndarray]:
        """The volume's own (vertices, faces), re-indexed from 0."""
        t = self.tris[vol.first:vol.last + 1]
        idx, inv = np.unique(t, return_inverse=True)
        return self.verts[idx], inv.reshape(t.shape)

    def write(self, output_path: Path, volumes: list[tuple[np.ndarray, np.ndarray, str]]) -> None:
        """Save a copy whose object consists of the given (vertices, faces, volume xml)
        triples: the existing volumes' xml (updated or not) in order, then any new ones.
        Triangle ranges are renumbered; the thumbnail is dropped since it would still
        show the template (PrusaSlicer regenerates one on save)."""
        all_v, all_t, config_parts = [], [], []
        for v, f, xml in volumes:
            base_v, base_t = sum(len(x) for x in all_v), sum(len(x) for x in all_t)
            all_v.append(v)
            all_t.append(f + base_v)
            config_parts.append(re.sub(r'^\s*<volume firstid="\d+" lastid="\d+">',
                                       f'<volume firstid="{base_t}" lastid="{base_t + len(f) - 1}">', xml))
        vertex_xml = "".join(f'     <vertex x="{x:.9g}" y="{y:.9g}" z="{z:.9g}"/>\n' for x, y, z in np.vstack(all_v))
        triangle_xml = "".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n' for a, b, c in np.vstack(all_t))
        model_xml = re.sub(r"<vertices>.*?</vertices>", lambda m: f"<vertices>\n{vertex_xml}    </vertices>", self.model_xml, flags=re.S)
        model_xml = re.sub(r"<triangles>.*?</triangles>", lambda m: f"<triangles>\n{triangle_xml}    </triangles>", model_xml, flags=re.S)

        config = self.config
        for old, new in zip(self.volumes, config_parts):
            config = config.replace(old.xml, new, 1)
        extra = "".join(f"  {xml}\n" for xml in config_parts[len(self.volumes):])
        config = config.replace(" </object>", f"{extra} </object>", 1)

        entries = dict(self.entries)
        entries["3D/3dmodel.model"] = model_xml.encode("utf-8")
        entries["Metadata/Slic3r_PE_model.config"] = config.encode("utf-8")
        entries.pop("Metadata/thumbnail.png", None)
        entries["_rels/.rels"] = re.sub(r'\s*<Relationship [^>]*thumbnail[^>]*/>', "",
                                        entries["_rels/.rels"].decode("utf-8")).encode("utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries.items():
                z.writestr(name, data)


def negative_volume_xml(name: str, v: np.ndarray) -> str:
    """Config entry for a plain (non-text-tool) negative volume; the triangle range is
    filled in by Project.write()."""
    center = (v.min(0) + v.max(0)) / 2
    return (
        '<volume firstid="0" lastid="0">\n'
        f'   <metadata type="volume" key="name" value="{escape(name)}"/>\n'
        '   <metadata type="volume" key="volume_type" value="NegativeVolume"/>\n'
        '   <metadata type="volume" key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
        f'   <metadata type="volume" key="source_offset_x" value="{center[0]:.15g}"/>\n'
        f'   <metadata type="volume" key="source_offset_y" value="{center[1]:.15g}"/>\n'
        f'   <metadata type="volume" key="source_offset_z" value="{center[2]:.15g}"/>\n'
        '   <mesh edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
        '  </volume>'
    )
