#!/usr/bin/env python3
# /// script
# dependencies = ["pillow", "numpy", "opencv-python-headless<5", "rembg[cpu]"]
# ///
"""
Turns a person's plain photo into a screen-print style portrait for the QR codes:
face-centred square crop, background cut out, and the tones flattened to three
levels (shadow / mid / light), so the face reads as a poster rather than a snapshot
once build_deck.py recolors it into the card gradient.

  uv run make_contrast.py <slug> [photo] [--lift-nose 0.3]

--lift-nose brightens the area around the nose tip before the tones are flattened (0..1,
~0.3 is subtle). For photos taken from below, where the nostrils and the shadow under the
nose otherwise turn into one big dark blob.

Reads people/<slug>/face_original.* (or the given photo) and writes
  people/<slug>/face.png            3 tones plus a flat background; what build_deck.py embeds
  people/<slug>/photo-contrast.png  the same bands as black / red / white — the format
                                    the archived relief pipeline (scripts/archive/
                                    make_heightmap.py) takes, previously drawn by hand

Rerun build_deck.py afterwards to get the new face onto the cards. The first run
downloads rembg's segmentation model (~170 MB, cached in ~/.u2net) and OpenCV's
YuNet face detector (~230 KB, cached in ~/.cache/musikster).
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.request import urlretrieve

import cv2
import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
PEOPLE_DIR = REPO_ROOT / "people"

# How much of the crop the detected face box takes up — leaves room for hair and
# shoulders so the circle in the QR isn't a tight mugshot.
FACE_FILL = 0.55
OUTPUT_SIZE = 800
# Fraction of foreground pixels that end up in the shadow / mid band; the rest are
# light. Percentiles rather than fixed thresholds so a dark or an overexposed photo
# still splits into three usable bands.
SHADOW_SHARE = 0.22
MID_SHARE = 0.30
# Gray values written to face.png (build_deck.py maps 0 -> full card gradient, 255 -> white).
# The background gets its own tone rather than white so the face sits in a filled disc in
# the QR code instead of dissolving into the code's white; the four tones are spread evenly.
LEVELS = (0, 150, 255)          # shadow / mid / light
BACKGROUND_LEVEL = 70
POSTER_COLORS = ((0, 0, 0), (255, 0, 0), (255, 255, 255))  # photo-contrast.png


def find_source(slug: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    person_dir = PEOPLE_DIR / slug
    if not (person_dir / "person.json").exists():
        sys.exit(f"No people/{slug}/person.json — see README.md \"Adding a person\".")
    for candidate in sorted(person_dir.glob("face_original.*")):
        return candidate
    sys.exit(f"No people/{slug}/face_original.* — drop the photo there (or pass a path).")


YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
YUNET_MODEL = Path.home() / ".cache" / "musikster" / "face_detection_yunet_2023mar.onnx"


def detect_face(img: np.ndarray) -> tuple[int, int, int, int, float, float] | None:
    """(x, y, w, h, nose_x, nose_y) of the largest face via OpenCV's YuNet, which copes
    with tilted heads where the classic Haar cascades give up. The ~230 KB model is
    fetched once."""
    if not YUNET_MODEL.exists():
        print("  downloading the YuNet face-detection model…")
        YUNET_MODEL.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(YUNET_URL, YUNET_MODEL)
    h, w = img.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (w, h), score_threshold=0.6)
    _, faces = detector.detect(img)
    if faces is None or len(faces) == 0:
        return None
    face = max(faces, key=lambda f: f[2] * f[3])
    x, y, fw, fh = face[:4]
    return int(x), int(y), int(fw), int(fh), float(face[8]), float(face[9])  # [8:10] = nose tip


def square_crop_on_face(img: np.ndarray) -> tuple[np.ndarray, tuple[float, float, float] | None]:
    """Square crop centred on the largest detected face (centre crop if none found), plus
    the nose tip and face width in crop pixels, or None without a face."""
    h, w = img.shape[:2]
    face = detect_face(img)
    nose = None
    if face is None:
        side = min(h, w)
        cx, cy = w // 2, h // 2
        print("  no face detected — using the centre of the photo")
    else:
        x, y, fw, fh, nose_x, nose_y = face
        cx, cy = x + fw // 2, y + fh // 2
        side = min(int(max(fw, fh) / FACE_FILL), min(h, w))
        print(f"  face at ({cx}, {cy}), box {fw}x{fh} — cropping {side}x{side} around it")
    left = int(np.clip(cx - side / 2, 0, w - side))
    top = int(np.clip(cy - side / 2, 0, h - side))
    if face is not None:
        nose = (nose_x - left, nose_y - top, float(fw))
    return img[top:top + side, left:left + side], nose


def lift_nose(img_bgr: np.ndarray, nose: tuple[float, float, float], amount: float) -> np.ndarray:
    """Brightens a soft spot around the nose tip. In photos taken from below, the
    nostrils and the shadow under the nose fall into the shadow band and print as one
    big dark blob; lifting them toward white first leaves a smaller nose with nostrils.
    amount 0..1 is how far toward white the centre of the spot goes."""
    nx, ny, face_w = nose
    r = face_w * 0.15
    yy, xx = np.mgrid[0:img_bgr.shape[0], 0:img_bgr.shape[1]]
    weight = np.exp(-((xx - nx) ** 2 + (yy - (ny + r * 0.2)) ** 2) / (2 * r * r)) * amount
    lifted = img_bgr.astype(np.float32)
    lifted += (255 - lifted) * weight[..., None]
    return lifted.astype(np.uint8)


def foreground_mask(img_bgr: np.ndarray) -> np.ndarray:
    """0..255 alpha of the person, background removed with rembg. Other people at the
    edge of the frame count as foreground too, so only the blob under the middle of
    the crop (where the face is) is kept."""
    from rembg import remove

    rgba = remove(Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)))
    alpha = np.array(rgba)[:, :, 3]
    # Fill pinholes, then keep the connected blob under the centre (fallback: largest).
    solid = cv2.morphologyEx((alpha > 128).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid)
    if count > 1:
        h, w = solid.shape
        centre_label = labels[h // 2, w // 2]
        keep = centre_label if centre_label != 0 else 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        alpha = np.where(labels == keep, alpha, 0).astype(np.uint8)
    # Soften the cut edge a touch so the outline isn't jagged.
    return cv2.GaussianBlur(alpha, (5, 5), 0)


def _smoothed_gray(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # Even out lighting, then smooth while keeping edges so the bands have clean borders.
    gray = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4)).apply(gray)
    for _ in range(2):  # repeated bilateral passes flatten skin texture, keep the outlines
        gray = cv2.bilateralFilter(gray, d=15, sigmaColor=30, sigmaSpace=10)
    return gray


def posterize(img_bgr: np.ndarray, alpha: np.ndarray, reference_bgr: np.ndarray | None = None) -> np.ndarray:
    """Three flat tone bands over the foreground; returns 0/1/2 per pixel (2 = light),
    with the background at 2. The band cut-offs come from reference_bgr when given (the
    untouched photo), so a local edit like lift_nose doesn't shift the whole face's bands."""
    gray = _smoothed_gray(img_bgr)
    reference = gray if reference_bgr is None else _smoothed_gray(reference_bgr)

    fg = reference[alpha > 128]
    shadow_cut = np.percentile(fg, SHADOW_SHARE * 100)
    mid_cut = np.percentile(fg, (SHADOW_SHARE + MID_SHARE) * 100)
    bands = np.full(gray.shape, 2, dtype=np.uint8)
    bands[gray <= mid_cut] = 1
    bands[gray <= shadow_cut] = 0
    # Drop speckles and thin slivers so the bands print as clean flat shapes.
    bands = cv2.medianBlur(bands, 7)
    bands[alpha <= 128] = 2
    return bands


def main() -> None:
    args = sys.argv[1:]
    nose_lift = 0.0
    if "--lift-nose" in args:
        i = args.index("--lift-nose")
        nose_lift = float(args[i + 1])
        del args[i:i + 2]
    if len(args) not in (1, 2):
        sys.exit("Usage: uv run make_contrast.py <slug> [photo] [--lift-nose 0.3]")
    slug = args[0]
    source = find_source(slug, args[1] if len(args) == 2 else None)
    out_dir = PEOPLE_DIR / slug

    img = cv2.imread(str(source))
    if img is None:
        sys.exit(f"Couldn't read {source}")
    print(f"Photo: {source.relative_to(REPO_ROOT) if source.is_relative_to(REPO_ROOT) else source} ({img.shape[1]}x{img.shape[0]})")

    img, nose = square_crop_on_face(img)
    scale = OUTPUT_SIZE / img.shape[0]
    img = cv2.resize(img, (OUTPUT_SIZE, OUTPUT_SIZE), interpolation=cv2.INTER_LANCZOS4)
    print("  removing background…")
    alpha = foreground_mask(img)
    if nose_lift and nose is not None:
        print(f"  lifting the nose shadow by {nose_lift}")
        nose = tuple(v * scale for v in nose)
        bands = posterize(lift_nose(img, nose, nose_lift), alpha, reference_bgr=img)
    else:
        if nose_lift:
            print("  no face detected — can't lift the nose, skipping")
        bands = posterize(img, alpha)
    for level, name in enumerate(("shadow", "mid", "light")):
        share = (bands == level).mean() * 100
        print(f"  {name}: {share:.0f}% of the image")

    face = np.array(LEVELS, dtype=np.uint8)[bands]
    face[alpha <= 128] = BACKGROUND_LEVEL
    Image.fromarray(face, "L").save(out_dir / "face.png")
    poster = np.array(POSTER_COLORS, dtype=np.uint8)[bands]
    Image.fromarray(poster, "RGB").save(out_dir / "photo-contrast.png")
    rel = out_dir.relative_to(REPO_ROOT)
    print(f"Wrote {rel}/face.png and {rel}/photo-contrast.png — rerun build_deck.py {slug} to use it.")


if __name__ == "__main__":
    main()
