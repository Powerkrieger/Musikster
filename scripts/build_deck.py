#!/usr/bin/env python3
"""
Builds one person's Hitster deck from their curated Spotify playlist, offline.

Everything about a person lives in people/<slug>/ (see README.md "Adding a person"),
which is meant to be its own private git repo:
  person.json        name, app name, greeting, playlist, card-id prefix, colors
  overrides.csv      manual release-year corrections (optional)
  face.png           photo composited into the center of every QR code (optional)
  assets/deck.json   generated here; bundled into the <slug> flavor by Gradle
  print/*.pdf        generated here; the printable card sheets

What it does:
  1. Logs into Spotify (PKCE, same client id as the app; opens your browser once).
  2. Reads every track in the person's playlist.
  3. Looks up each track's release year via the free iTunes Search API,
     applying any corrections from overrides.csv.
  4. Writes people/<slug>/assets/deck.json — app/build.gradle.kts wires that
     directory in as the <slug> flavor's assets, so rebuild/reinstall that
     flavor to pick it up.
  5. Renders printable A4 PDFs into people/<slug>/print/: the deck (standardized
     QR-code front sheets alternating with gradient title/artist/year back sheets,
     sized for a 3x4 duplex print job) and a separate line sheet (the cutting
     guide, printed once on plain paper).

Card ids (the QR payload) are prefixed with the person's slug ("nils-001") unless
person.json sets "cardIdPrefix" otherwise, so decks from different people can be
shuffled together in one game without two cards sharing an id.

Usage:
    cd scripts
    uv run build_deck.py <slug> [playlist_url_or_id]

The playlist normally comes from person.json; passing one on the command line
overrides it for this run.

Requires SPOTIFY_CLIENT_ID — read automatically from local.properties (the
same value the Android app uses) unless the SPOTIFY_CLIENT_ID env var is set.
See the repo's README.md ("Building the deck") for one-time setup (Spotify
dashboard redirect URI, installing uv).
"""
from __future__ import annotations

import csv
import hashlib
import base64
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO_ROOT = Path(__file__).resolve().parent.parent
PEOPLE_DIR = REPO_ROOT / "people"

REDIRECT_PORT = 8927
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

CARDS_PER_ROW = 3
CARDS_PER_COL = 4
CARDS_PER_PAGE = CARDS_PER_ROW * CARDS_PER_COL
PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 portrait, points at 72dpi
MARGIN = 24

# Default card-back gradient (green -> blue diagonal, matching the original
# card-design reference doc); person.json "printGradient" overrides it. A middle
# stop (rather than a plain 2-color lerp) keeps the first color as a real band
# across the card instead of just a sliver in the corner, so the two colors read
# as evenly balanced rather than one dominating.
DEFAULT_GRADIENT_STOPS = [
    (72, 209, 121),   # green
    (46, 176, 155),   # green-teal midpoint
    (46, 108, 214),   # blue
]

Rgb = tuple[int, int, int]


@dataclass
class Person:
    """One recipient, as described by people/<slug>/person.json."""
    slug: str
    name: str
    playlist: str | None
    card_id_prefix: str
    gradient_stops: list[Rgb]

    @property
    def dir(self) -> Path:
        return PEOPLE_DIR / self.slug

    @property
    def overrides_csv(self) -> Path:
        return self.dir / "overrides.csv"

    @property
    def face_photo(self) -> Path:
        return self.dir / "face.png"

    @property
    def assets_deck_json(self) -> Path:
        return self.dir / "assets" / "deck.json"

    @property
    def output_dir(self) -> Path:
        return self.dir / "print"

    @property
    def output_pdf(self) -> Path:
        return self.output_dir / f"musikster_{self.slug}_deck.pdf"

    @property
    def output_line_sheet_pdf(self) -> Path:
        return self.output_dir / f"musikster_{self.slug}_line_sheet.pdf"

    @property
    def output_combined_pdf(self) -> Path:
        return self.output_dir / f"musikster_{self.slug}_deck_with_line_sheet.pdf"


def load_person(slug: str) -> Person:
    config_path = PEOPLE_DIR / slug / "person.json"
    if not re.fullmatch(r"[a-z][a-z0-9]*", slug) or not config_path.exists():
        available = sorted(p.parent.name for p in PEOPLE_DIR.glob("*/person.json"))
        sys.exit(
            f"No people/{slug}/person.json. Known people: {', '.join(available) or '(none)'} — "
            "see README.md \"Adding a person\"."
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    stops = config.get("printGradient") or DEFAULT_GRADIENT_STOPS
    if len(stops) < 2 or any(len(stop) != 3 for stop in stops):
        sys.exit(f"{config_path}: printGradient must be a list of at least two [r, g, b] triples.")
    return Person(
        slug=slug,
        name=config.get("name") or slug,
        playlist=config.get("playlist") or None,
        # Absent -> "<slug>-"; an explicit "" keeps bare "001" ids (the first deck, whose
        # cards were printed before ids carried a prefix).
        card_id_prefix=config["cardIdPrefix"] if "cardIdPrefix" in config else f"{slug}-",
        gradient_stops=[tuple(int(v) for v in stop) for stop in stops],
    )


def read_client_id() -> str:
    env_value = os.environ.get("SPOTIFY_CLIENT_ID")
    if env_value:
        return env_value
    local_props = REPO_ROOT / "local.properties"
    if local_props.exists():
        for line in local_props.read_text().splitlines():
            if line.strip().startswith("SPOTIFY_CLIENT_ID="):
                return line.split("=", 1)[1].strip()
    sys.exit(
        "No Spotify client id found. Set SPOTIFY_CLIENT_ID, or add it to "
        "local.properties (see scripts/README.md)."
    )


def extract_playlist_id(playlist_input: str) -> str:
    s = playlist_input.strip()
    m = re.search(r"spotify\.com/playlist/([A-Za-z0-9]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"spotify:playlist:([A-Za-z0-9]+)", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{15,30}", s):
        return s
    sys.exit(f"'{playlist_input}' doesn't look like a playlist URL or ID.")


# ---------------------------------------------------------------------------
# PKCE auth (mirrors SpotifyAuthManager.kt, adapted for a one-shot local script)
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_login(client_id: str, scopes: str = SCOPES) -> str:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())

    auth_url = AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": scopes,
        "show_dialog": "true",
    })

    result: dict[str, str] = {}
    done = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            code = query.get("code", [None])[0]
            error = query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if code:
                result["code"] = code
                self.wfile.write(b"<html><body>Logged in, you can close this tab.</body></html>")
            else:
                result["error"] = error or "unknown_error"
                self.wfile.write(b"<html><body>Login failed, check the terminal.</body></html>")
            done.set()

        def log_message(self, *args):
            pass  # keep stdout clean

    server = HTTPServer(("127.0.0.1", REDIRECT_PORT), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print("Opening Spotify login in your browser…")
    print(f"  (if no tab opens, paste this URL into a browser: {auth_url})")
    webbrowser.open(auth_url)
    if not done.wait(timeout=180):
        server.shutdown()
        sys.exit("Timed out waiting for Spotify login.")
    server.shutdown()

    if "error" in result:
        sys.exit(f"Spotify login failed: {result['error']}")

    body = urlencode({
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode("utf-8")
    req = Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req) as resp:
        token_json = json.loads(resp.read())
    print(f"  granted scope: {token_json.get('scope', '?')}")
    return token_json["access_token"]


# ---------------------------------------------------------------------------
# Spotify Web API — playlist tracks (mirrors SpotifyWebApi.kt)
# ---------------------------------------------------------------------------

@dataclass
class PlaylistTrack:
    spotify_track_id: str
    uri: str
    name: str
    artist: str
    album_art_url: str | None


def fetch_playlist_tracks(playlist_id: str, access_token: str) -> list[PlaylistTrack]:
    """GET /playlists/{id}/items — the current replacement for the deprecated /tracks
    sub-resource (which 403s). Each item's track/episode data lives under the "item" key
    (the old "track" key is a deprecated back-compat alias). limit maxes out at 50.
    """
    fields = "items(item(id,uri,name,type,artists(name),album(images))),next"
    limit = 50
    url = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        f"?limit={limit}&offset=0&fields={urlencode({'': fields})[1:]}"
    )
    tracks: list[PlaylistTrack] = []

    while url:
        req = Request(url, headers={"Authorization": f"Bearer {access_token}"})
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read())
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            sys.exit(f"Spotify API error fetching playlist tracks: {e.code} {e.reason}\n{body}")

        for entry in data.get("items", []):
            track = entry.get("item")
            if not track or track.get("type") != "track" or not track.get("id"):
                continue
            artists = ", ".join(a["name"] for a in track.get("artists", [])) or "Unknown"
            images = track.get("album", {}).get("images") or []
            art_url = images[0]["url"] if images else None
            tracks.append(PlaylistTrack(
                spotify_track_id=track["id"],
                uri=track.get("uri", ""),
                name=track.get("name") or "Unknown",
                artist=artists,
                album_art_url=art_url,
            ))

        url = data.get("next") or None

    return _dedupe_tracks(tracks)


def _dedupe_tracks(tracks: list[PlaylistTrack]) -> list[PlaylistTrack]:
    """Drop repeat catalog entries of the same recording — e.g. a song that's on
    the playlist once from the standard album and once from a deluxe/reissue
    edition, under two different Spotify track ids. Same title + artist, first
    occurrence wins.
    """
    seen: set[str] = set()
    deduped = []
    for track in tracks:
        key = f"{track.name}|{track.artist}".lower()
        if key in seen:
            print(f"  (dropping duplicate: {track.artist} - {track.name})")
            continue
        seen.add(key)
        deduped.append(track)
    return deduped


# ---------------------------------------------------------------------------
# iTunes year lookup (mirrors ITunesApi.kt) + manual overrides
# ---------------------------------------------------------------------------

def load_overrides(overrides_csv: Path) -> dict[str, int]:
    """overrides.csv rows: key,year — key is a Spotify track id, or 'Song Name|Artist'."""
    if not overrides_csv.exists():
        return {}
    overrides: dict[str, int] = {}
    with overrides_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("key") or "").strip()
            year_str = (row.get("year") or "").strip()
            if not key or not year_str:
                continue
            overrides[key.lower()] = int(year_str)
    return overrides


def lookup_year(track: PlaylistTrack, overrides: dict[str, int]) -> int | None:
    for key in (track.spotify_track_id.lower(), f"{track.name}|{track.artist}".lower()):
        if key in overrides:
            return overrides[key]

    query = urlencode({"term": f"{track.artist} {track.name}", "entity": "song", "limit": "5"})
    url = f"https://itunes.apple.com/search?{query}"

    # iTunes' free endpoint throttles intermittently under sustained use (not a hard
    # per-request limit — short bursts are fine, but a ~100-song deck run back to back
    # trips it partway through). Retry with backoff before giving up on a track.
    last_error = None
    for attempt in range(4):
        if attempt > 0:
            time.sleep(2 ** attempt)  # 2s, 4s, 8s
        try:
            with urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            results = data.get("results") or []
            if results:
                release_date = results[0].get("releaseDate", "")
                year_str = release_date.split("-")[0] if release_date else ""
                return int(year_str) if year_str.isdigit() else None
            return None  # genuinely no match — not a transient failure, don't retry
        except HTTPError as e:
            last_error = f"HTTP {e.code}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

    print(f"    (year lookup failed for {track.artist} - {track.name} after retries: {last_error})")
    return None


# ---------------------------------------------------------------------------
# deck.json (mirrors DeckModels.kt's Card/Deck schema exactly)
# ---------------------------------------------------------------------------

def build_cards(tracks: list[PlaylistTrack], overrides: dict[str, int], card_id_prefix: str) -> list[dict]:
    id_width = max(3, len(str(len(tracks))))
    cards = []
    for index, track in enumerate(tracks):
        year = lookup_year(track, overrides)
        print(f"  [{index + 1}/{len(tracks)}] {track.artist} - {track.name} ({year or '?'})")
        cards.append({
            "cardId": card_id_prefix + str(index + 1).zfill(id_width),
            "spotifyTrackId": track.spotify_track_id,
            "spotifyUri": track.uri,
            "name": track.name,
            "artist": track.artist,
            "year": year,
            "albumArtUrl": track.album_art_url,
        })
        # iTunes' free search endpoint has an informal per-IP rate limit; pace
        # requests so a ~100-song deck doesn't start failing partway through.
        time.sleep(0.35)
    return cards


def write_deck_json(person: Person, playlist_id: str, cards: list[dict]) -> None:
    deck = {
        # deckId is what the app dedupes imports by; name is what its deck list shows.
        "deckId": person.slug,
        "name": person.name,
        "createdAt": int(time.time() * 1000),
        "playlistId": playlist_id,
        "cards": cards,
    }
    person.assets_deck_json.parent.mkdir(parents=True, exist_ok=True)
    person.assets_deck_json.write_text(json.dumps(deck, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Printable PDF (mirrors DeckPdfGenerator.kt + QrCodeGenerator.kt)
# ---------------------------------------------------------------------------

def generate_pdf(person: Person, cards: list[dict]) -> None:
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.lib.utils import ImageReader

    if not person.face_photo.exists():
        print(
            f"  Note: no photo at {person.face_photo.relative_to(REPO_ROOT)} — "
            "QR codes will be plain. Drop a square-ish photo there and rerun to add it."
        )

    cell_w = (PAGE_WIDTH - 2 * MARGIN) / CARDS_PER_ROW
    cell_h = (PAGE_HEIGHT - 2 * MARGIN) / CARDS_PER_COL

    gradient_reader = ImageReader(_gradient_image(person.gradient_stops))

    person.output_dir.mkdir(parents=True, exist_ok=True)

    # Printed on plain paper, not the card stock: card sheets carry no cut lines
    # of their own (duplex-print misregistration made them land crooked against
    # the actual cut), so this sheet is the one source of truth to cut against —
    # lay a printed card sheet under it and cut along its lines. Kept as its own
    # PDF (rather than a leading page of the deck) since it's printed once on
    # plain paper, not duplexed onto the card stock like the rest.
    line_sheet = pdfcanvas.Canvas(str(person.output_line_sheet_pdf), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    _draw_cutting_guide_page(line_sheet, cell_w, cell_h)
    line_sheet.showPage()
    line_sheet.save()

    deck = pdfcanvas.Canvas(str(person.output_pdf), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    _draw_deck_pages(deck, person, cards, cell_w, cell_h, gradient_reader)
    deck.save()

    # Same deck pages plus the cutting guide appended as a last page, for anyone
    # who'd rather print/share one file than juggle two.
    combined = pdfcanvas.Canvas(str(person.output_combined_pdf), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    _draw_deck_pages(combined, person, cards, cell_w, cell_h, gradient_reader)
    _draw_cutting_guide_page(combined, cell_w, cell_h)
    combined.showPage()
    combined.save()


def _draw_deck_pages(c, person, cards, cell_w, cell_h, gradient_reader) -> None:
    def draw_front_cell(c, card, left, top, w, h):
        _draw_front_cell(c, person, card, left, top, w, h)

    for page_cards in _chunk(cards, CARDS_PER_PAGE):
        # Front (QR side): standardized plain white background — only the QR differs card to card.
        _draw_page(c, page_cards, cell_w, cell_h, None, draw_front_cell)
        c.showPage()

        # Back (answer side): the gradient card design.
        mirrored = [card for row in _chunk(page_cards, CARDS_PER_ROW) for card in reversed(row)]
        _draw_page(c, mirrored, cell_w, cell_h, gradient_reader, _draw_back_cell)
        c.showPage()


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _gradient_color(t: float, stops: list[Rgb]) -> Rgb:
    """t in [0, 1] across stops, interpolating piecewise between consecutive stops."""
    segments = len(stops) - 1
    pos = min(t, 1.0) * segments
    seg = min(int(pos), segments - 1)
    local_t = pos - seg
    a, b = stops[seg], stops[seg + 1]
    return tuple(int(a[i] + (b[i] - a[i]) * local_t) for i in range(3))


def _gradient_image(stops: list[Rgb], size=800):
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = _gradient_color(t, stops)
    return img


def _draw_page(c, page_cards, cell_w, cell_h, background, draw_cell) -> None:
    if background is not None:
        c.drawImage(background, 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)
    for index, card in enumerate(page_cards):
        row = index // CARDS_PER_ROW
        col = index % CARDS_PER_ROW
        left = MARGIN + col * cell_w
        # PDF y-axis is bottom-up; row 0 must be the top row.
        top = PAGE_HEIGHT - MARGIN - (row + 1) * cell_h
        draw_cell(c, card, left, top, cell_w, cell_h)


def _draw_cutting_guide_page(c, cell_w, cell_h) -> None:
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.setFont("Helvetica", 10)
    c.drawCentredString(
        PAGE_WIDTH / 2, PAGE_HEIGHT - MARGIN / 2,
        "Cutting guide — lay a printed sheet underneath and cut along these lines",
    )
    for row in range(CARDS_PER_COL):
        for col in range(CARDS_PER_ROW):
            left = MARGIN + col * cell_w
            top = PAGE_HEIGHT - MARGIN - (row + 1) * cell_h
            _draw_cut_guide(c, left, top, cell_w, cell_h)


def _draw_cut_guide(c, left, top, w, h) -> None:
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.setLineWidth(0.75)
    c.rect(left, top, w, h, stroke=1, fill=0)


def _draw_front_cell(c, person, card, left, top, w, h) -> None:
    from reportlab.lib.utils import ImageReader

    qr_img = _qr_with_face(card["cardId"], person)
    qr_size = min(w, h) * 0.78
    cx, cy = left + w / 2, top + h / 2
    c.drawImage(ImageReader(qr_img), cx - qr_size / 2, cy - qr_size / 2, width=qr_size, height=qr_size)


QR_VERSION = 6  # fixed at 41x41 modules — far finer than "nils-001" needs on its own,
                # which is what gives the code its dense, detailed look instead of a
                # coarse minimum-size block.
QR_RESERVE_MODULES = 13  # centered square of modules left blank for the photo (~10%
                          # of the grid — well inside H-level's 30% recoverable budget)


def _duotone(face, size, stops: list[Rgb]):
    """Resize to a square, convert to black-and-white, then recolor black
    toward the same pastel gradient the card backs use (white stays white) —
    so the embedded photo reads as part of the deck's palette instead of a
    plain color snapshot.
    """
    from PIL import Image as PILImage

    face = face.resize((size, size), PILImage.LANCZOS)
    grayscale = face.convert("L")
    white = PILImage.new("RGB", (size, size), (255, 255, 255))
    gradient = _gradient_image(stops, size)
    return PILImage.composite(white, gradient, grayscale)


def _qr_with_face(data: str, person: Person):
    """A QR code with a real reserved blank square in the center for the person's
    photo, rather than the photo simply painted over live data modules afterwards.
    High error correction (H, 30% recoverable) plus a fixed symbol version much
    larger than the tiny card-id payload needs gives enough redundancy to blank a
    centered square of modules and still decode reliably.
    """
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H
    from PIL import Image as PILImage, ImageDraw

    qr = qrcode.QRCode(version=QR_VERSION, error_correction=ERROR_CORRECT_H, box_size=14, border=0)
    qr.add_data(data)
    qr.make(fit=False)

    n = qr.modules_count
    lo = (n - QR_RESERVE_MODULES) // 2
    hi = lo + QR_RESERVE_MODULES
    for r in range(lo, hi):
        for c in range(lo, hi):
            qr.modules[r][c] = False

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    if not person.face_photo.exists():
        return img

    face = PILImage.open(person.face_photo).convert("RGB")
    side = min(face.size)
    left = (face.width - side) // 2
    top = (face.height - side) // 2
    face = face.crop((left, top, left + side, top + side))

    # Fit the photo inside the reserved square, leaving a slim white margin
    # around it so the circular crop doesn't touch the surrounding modules.
    reserved_px = QR_RESERVE_MODULES * qr.box_size
    face_size = int(reserved_px * 0.86)
    face = _duotone(face, face_size, person.gradient_stops)
    face_mask = PILImage.new("L", (face_size, face_size), 0)
    ImageDraw.Draw(face_mask).ellipse((0, 0, face_size, face_size), fill=255)

    cx, cy = img.width // 2, img.height // 2
    img.paste(face, (cx - face_size // 2, cy - face_size // 2), face_mask)

    return img


def _draw_back_cell(c, card, left, top, w, h) -> None:
    padding = 10
    max_width = w - 2 * padding
    cx = left + w / 2

    y = top + h - padding - 13
    y = _draw_title(c, card["name"], cx, y, max_width, "Helvetica-Bold", 13, (0, 0, 0))
    y -= 4
    y = _draw_wrapped(c, card["artist"], cx, y, max_width, "Helvetica", 11, (0.27, 0.27, 0.27))

    # Year fills the rest of the cell below the title/artist block, centered
    # in that remaining band rather than pinned to the bottom edge.
    year_text = str(card["year"]) if card["year"] else "?"
    year_size = 36
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", year_size)
    band_top, band_bottom = y, top + padding
    year_y = (band_top + band_bottom) / 2 - year_size * 0.32
    c.drawCentredString(cx, year_y, year_text)


def _draw_title(c, title, cx, start_y, max_width, font, size, rgb) -> float:
    """Titles with a parenthetical — '(feat. X)', '(From the Netflix Film ...)',
    '(Radio Version)', etc — get a forced line break before the '(' so the
    parenthetical reads as its own line instead of running on from the song
    name. Only applied when it doesn't cost extra lines versus plain greedy
    wrapping: a short title like 'Titanium (feat. Sia)' already fits on one
    line on its own, so forcing a break there would make it worse, not better.
    """
    c.setFont(font, size)
    idx = title.find(" (")
    if idx != -1:
        name, citation = title[:idx], title[idx + 1:]
        natural = _wrap_lines(c, title, font, size, max_width)
        forced = _wrap_lines(c, name, font, size, max_width) + _wrap_lines(c, citation, font, size, max_width)
        if len(forced) <= len(natural):
            return _draw_lines(c, forced, cx, start_y, size, rgb)
    return _draw_wrapped(c, title, cx, start_y, max_width, font, size, rgb)


def _wrap_lines(c, text, font, size, max_width) -> list[str]:
    words = text.split(" ")
    lines = []
    line = ""
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if c.stringWidth(candidate, font, size) > max_width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _draw_lines(c, lines, cx, start_y, size, rgb) -> float:
    c.setFillColorRGB(*rgb)
    y = start_y
    line_height = size + 3
    for line in lines:
        c.drawCentredString(cx, y, line)
        y -= line_height
    return y


def _draw_wrapped(c, text, cx, start_y, max_width, font, size, rgb) -> float:
    c.setFont(font, size)
    return _draw_lines(c, _wrap_lines(c, text, font, size, max_width), cx, start_y, size, rgb)


# ---------------------------------------------------------------------------

def print_identity(access_token: str) -> None:
    """Confirms which Spotify account is logged in — playlist access is scoped to what
    that account owns/can see, so this is worth a glance if a fetch ever 403s."""
    req = Request("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urlopen(req) as resp:
            me = json.loads(resp.read())
        print(f"Logged in as: {me.get('display_name')} ({me.get('id')})")
    except HTTPError as e:
        print(f"  (couldn't fetch /v1/me: {e.code} {e.reason})")


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: uv run build_deck.py <slug> [playlist_url_or_id]")

    person = load_person(sys.argv[1])
    playlist_input = sys.argv[2] if len(sys.argv) == 3 else person.playlist
    if not playlist_input:
        sys.exit(f"people/{person.slug}/person.json has no \"playlist\" — add one or pass it as the 2nd argument.")

    client_id = read_client_id()
    playlist_id = extract_playlist_id(playlist_input)
    overrides = load_overrides(person.overrides_csv)
    print(f"Building {person.name}'s deck (card ids: '{person.card_id_prefix}001'…)")

    access_token = pkce_login(client_id)
    print_identity(access_token)

    print("Reading playlist…")
    tracks = fetch_playlist_tracks(playlist_id, access_token)
    if not tracks:
        sys.exit("Couldn't read any tracks from that playlist.")
    print(f"Found {len(tracks)} tracks. Looking up release years…")

    cards = build_cards(tracks, overrides, person.card_id_prefix)

    write_deck_json(person, playlist_id, cards)
    print(
        f"Wrote {person.assets_deck_json.relative_to(REPO_ROOT)} — "
        f"rebuild/reinstall the '{person.slug}' flavor to pick it up."
    )

    print("Laying out printable PDFs…")
    generate_pdf(person, cards)
    rel = lambda p: p.relative_to(REPO_ROOT)  # noqa: E731
    print(f"Wrote {rel(person.output_line_sheet_pdf)} — print once on plain paper, cut guide only.")
    print(f"Wrote {rel(person.output_pdf)} — print a single page first and check alignment (see README.md).")
    print(f"Wrote {rel(person.output_combined_pdf)} — same deck with the cut guide appended as a last page.")


if __name__ == "__main__":
    main()
