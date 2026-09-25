#!/usr/bin/env python3
"""
Renders the one-page A5 manual that goes into the box with the cards: a German birthday
greeting plus how to get the app, Spotify, the deck and the rules.

Usage:
    cd scripts
    uv run make_manual.py <slug>

Reads people/<slug>/person.json; the optional "manual" object holds the personal parts:
    "manual": {
      "age": 17,                    # "Alles Gute zum 17. Geburtstag" (omit for no number)
      "wishes": "Wir wünschen dir …"  # the birthday-wish paragraph (a generic one otherwise)
    }
Writes people/<slug>/print/musikster_<slug>_anleitung.pdf. Besides the text it has a QR code
for the GitHub releases page and a "Deine Karten" section: an info row (from
people/<slug>/analysis/stats.json when make_overview.py wrote one — that knows English songs
and female leads — else just what the years tell) and a bar per release year, read from the
deck file. A strip under the closing line is left blank for signing by hand.

The closing emoji is drawn as a padded PNG cut from Noto Color Emoji rather than typeset
as text: PDF viewers clip a color-emoji glyph at its font box, which shows up as a
wink cut off at the bottom/right.
"""
from __future__ import annotations

import gzip
import json
from datetime import date
import statistics
import sys
import tempfile
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Frame, Image as RLImage, Paragraph, Spacer, Table, TableStyle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_deck import _duotone, load_person  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
APP_ICON = REPO / "app/src/main/res/mipmap-xxxhdpi/ic_launcher.webp"
RELEASES_URL = "github.com/Powerkrieger/Musikster/releases"
FONT_DIR = Path("/usr/share/fonts/truetype/noto")
EMOJI_FONT = FONT_DIR / "NotoColorEmoji.ttf"

CLOSING = ("Damit du eine Version hast, die deinen Musikgeschmack besser trifft und "
           "gleichzeitig deinen musikalischen Horizont erweiterst")
DEFAULT_WISHES = ("Wir wünschen dir ein Jahr voller guter Musik, lauter Konzerte, langer "
                  "Abende und Menschen, mit denen du jeden Refrain mitsingen kannst.")

MARGIN = 11 * mm
INK = HexColor("#1A1A1A")
MUTED = HexColor("#555555")
GRID = HexColor("#D9D9D9")
SIGNATURE_SPACE = 9 * mm  # blank strip under the closing line, for signing by hand

# Labels for the info row (make_overview.py writes them in English to analysis/stats.json).
STAT_LABELS_DE = {"Cards": "Karten", "Range": "Zeitraum", "Median": "Median", "Std. dev.": "Streuung",
                  "Before 2000": "vor 2000", "English": "Englisch", "Female lead (+duets)": "Sängerin (+Duett)"}


class YearChart(Flowable):
    """One thin bar per release year (every year from the first decade on, empty ones
    included), labelled every ten years — how the person's cards spread over time."""

    def __init__(self, years: list[int], width: float, height: float, color):
        super().__init__()
        self.years, self.width, self.height, self.color = years, width, height, color

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        first, last = min(self.years) // 10 * 10, max(self.years)
        counts = {y: self.years.count(y) for y in range(first, last + 1)}
        label_h = 9  # pt below the baseline for the decade labels
        plot_h = self.height - label_h - 2
        top = max(counts.values())
        slot = self.width / len(counts)
        c.setStrokeColor(GRID)
        c.setLineWidth(0.5)
        c.line(0, label_h, self.width, label_h)
        c.setFillColor(self.color)
        for i, (year, n) in enumerate(counts.items()):
            if n:
                c.rect(i * slot + slot * 0.12, label_h, slot * 0.76, n / top * plot_h, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont("NotoSans", 6.5)
        for i, year in enumerate(counts):
            if year % 10 == 0:
                c.drawCentredString(i * slot + slot / 2, 1.5, str(year))


def deck_years(person) -> list[int]:
    """Release years of the person's cards, read from the deck file build_deck.py wrote."""
    data = person.deck_file.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return [c["year"] for c in json.loads(data)["cards"] if c.get("year")]


def info_row(person, years: list[int], birth_year: int | None) -> list[tuple[str, str]]:
    """(value, label) tiles for the deck: the analysis' own row when there is one (it also
    knows English songs and female leads), otherwise what the years alone can tell. With a
    birth year, "before 2000" becomes "before <the year they were born>" — for a birthday
    card, how many of the songs are older than the person."""
    stats_file = person.dir / "analysis" / "stats.json"
    if stats_file.exists():
        tiles = [(s["value"].replace(" yrs", " J."), STAT_LABELS_DE.get(s["label"], s["label"]))
                 for s in json.loads(stats_file.read_text())]
    else:
        tiles = [(str(len(years)), "Karten"), (f"{min(years)}–{max(years)}", "Zeitraum"),
                 (str(int(statistics.median(years))), "Median"),
                 (f"±{round(statistics.pstdev(years))} J.", "Streuung"),
                 (str(sum(y < 2000 for y in years)), "vor 2000")]
    if birth_year:
        tiles = [(str(sum(y < birth_year for y in years)), f"vor {birth_year}") if label == "vor 2000"
                 else (value, label) for value, label in tiles]
    return tiles


def qr_png(url: str, out: Path) -> Path:
    import qrcode
    qrcode.make(url, border=1).save(out)
    return out


def emoji_png(char: str, out: Path) -> Path:
    """Noto Color Emoji only has a 109 px bitmap strike; render at that size on a canvas
    with generous room, then crop to the actual pixels plus a margin so nothing clips."""
    font = ImageFont.truetype(str(EMOJI_FONT), 109)
    canvas = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((40, 40), char, font=font, embedded_color=True)
    left, top, right, bottom = canvas.getbbox()
    pad = 6
    canvas.crop((left - pad, top - pad, right + pad, bottom + pad)).save(out)
    return out


def app_icon_png(out: Path) -> Path:
    Image.open(APP_ICON).convert("RGBA").save(out)
    return out


def face_icon_png(person, out: Path, size: int = 600) -> Path:
    """The person's portrait as a round badge, tinted into the card gradient exactly like
    the photo in the middle of the QR codes, so the manual matches the deck."""
    face = Image.open(person.face_photo).convert("RGB")
    side = min(face.size)
    left, top = (face.width - side) // 2, (face.height - side) // 2
    face = _duotone(face.crop((left, top, left + side, top + side)), size, person.gradient_stops)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    face.putalpha(mask)
    face.save(out)
    return out


def build(slug: str) -> Path:
    person = load_person(slug)
    config = json.loads((person.dir / "person.json").read_text())
    manual = config.get("manual", {})
    app_name = config.get("appName") or f"{person.name}'s Musikster"
    age = manual.get("age")
    wishes = manual.get("wishes", DEFAULT_WISHES)
    name = person.name
    deck_file = person.deck_file.name

    pdfmetrics.registerFont(TTFont("NotoSans", str(FONT_DIR / "NotoSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("NotoSans-Bold", str(FONT_DIR / "NotoSans-Bold.ttf")))
    registerFontFamily("NotoSans", normal="NotoSans", bold="NotoSans-Bold")

    body = ParagraphStyle("body", fontName="NotoSans", fontSize=8.6, leading=11.2,
                          textColor=INK, spaceAfter=3.5)
    head = ParagraphStyle("head", parent=body, fontName="NotoSans-Bold", fontSize=9.6,
                          leading=12, spaceBefore=3, spaceAfter=1.5)
    title = ParagraphStyle("title", parent=body, fontName="NotoSans-Bold", fontSize=15,
                           leading=19, alignment=1, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=body, alignment=1, textColor=MUTED, spaceAfter=6)
    closing = ParagraphStyle("closing", parent=body, fontName="NotoSans-Bold", leading=14)

    person.output_dir.mkdir(parents=True, exist_ok=True)
    out = person.output_dir / f"musikster_{slug}_anleitung.pdf"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # The person's face when there is one (same look as on the QR codes), else the app icon.
        if person.face_photo.exists():
            icon = face_icon_png(person, tmp / "icon.png")
        else:
            icon = app_icon_png(tmp / "icon.png")
        wink = emoji_png("😉", tmp / "wink.png")
        wink_w, wink_h = Image.open(wink).size
        wink_size = 11.5  # pt, a little over the cap height of the closing line

        # "Die App": the text next to a QR code for the releases page.
        qr_size = 14 * mm
        app_text = Paragraph("Deine Version bekommst du von uns. Eine allgemeine gibt es auf GitHub unter "
                             f"„Releases“: <b>{RELEASES_URL}</b> – oder einfach den Code scannen.", body)
        app_row = Table([[app_text, RLImage(str(qr_png("https://" + RELEASES_URL, tmp / "qr.png")),
                                            width=qr_size, height=qr_size)]],
                        colWidths=[A5[0] - 2 * MARGIN - qr_size - 3 * mm, qr_size + 3 * mm])
        app_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                     ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))

        # "Deine Karten": the deck's year distribution, bars in the card-back colour
        # (the gradient's last stop, darkened so it holds up on white paper).
        years = deck_years(person)
        r, g, b = (v * 0.8 / 255 for v in person.gradient_stops[-1])
        from reportlab.lib.colors import Color
        chart = YearChart(years, A5[0] - 2 * MARGIN, 14 * mm, Color(r, g, b))
        tile_v = ParagraphStyle("tile_v", parent=body, fontName="NotoSans-Bold", fontSize=9.5, leading=11,
                                alignment=1, spaceAfter=0)
        tile_l = ParagraphStyle("tile_l", parent=body, fontSize=5.8, leading=7, textColor=MUTED,
                                alignment=1, spaceAfter=0)
        # Born this many years ago: person.json "manual" can give "birthYear", else it's
        # worked out from "age" (the card is for this year's birthday).
        birth_year = manual.get("birthYear") or (date.today().year - age if age else None)
        tiles = info_row(person, years, birth_year)
        stats_row = Table([[Paragraph(escape(v), tile_v) for v, _ in tiles],
                           [Paragraph(escape(l), tile_l) for _, l in tiles]],
                          colWidths=[(A5[0] - 2 * MARGIN) / len(tiles)] * len(tiles))
        stats_row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                       ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 1), (-1, 1), 3)]))

        headline = f"Alles Gute zum {age}. Geburtstag, {name}!" if age else f"Alles Gute, {name}!"
        story = [
            RLImage(str(icon), width=15 * mm, height=15 * mm),
            Spacer(1, 1.5 * mm),
            Paragraph(escape(headline), title),
            Paragraph(f"Das hier ist <b>{escape(app_name)}</b> – dein eigenes Musik-Quiz "
                      "im Stil von Hitster.", sub),
            Paragraph(escape(wishes), body),

            Paragraph("Die App", head),
            app_row,

            Paragraph("Spotify", head),
            Paragraph("Die Songs laufen über die Spotify-App auf deinem Handy – dafür brauchst du ein "
                      "<b>Premium</b>-Konto.", body),

            Paragraph("Das Deck", head),
            Paragraph(f"Lade die Datei <b>{deck_file}</b>, die wir dir schicken, auf dem Startbildschirm "
                      "mit „Import Deck“ – und gib sie gern weiter, dann kann jede Musikster-App mit deinen "
                      "Karten spielen. Fast alle Songs sind deine Lieblingssongs, ein paar haben wir "
                      "dazugeschmuggelt.", body),

            Paragraph("So wird gespielt", head),
            Paragraph("<b>Erste Runde:</b> Alle ziehen eine Karte und hören den Song – ohne Jahr raten. "
                      "Umgedreht ist sie der Anfang der eigenen Zeitleiste. <b>Danach:</b> Wer dran ist, "
                      "scannt eine neue Karte, hört den Song und legt sie in die eigene Zeitleiste – vor, "
                      "zwischen oder hinter die Karten, die schon liegen. Dann umdrehen: Stimmt das Jahr, "
                      "bleibt sie liegen, sonst fliegt sie raus. Wer zuerst 10 Karten hat, gewinnt.", body),
            Paragraph("<b>Münzen:</b> Wer dran ist und Interpret <i>und</i> Titel richtig nennt, bekommt "
                      "eine Münze – auch schon in der ersten Runde. Mit einer Münze kannst du einen Song "
                      "überspringen, oder eine Karte klauen: Glaubst du, jemand hat falsch gelegt, setz "
                      "deine Münze an die richtige Stelle in seiner Zeitleiste, bevor umgedreht wird. "
                      "Stimmt das, kommt die Karte in deine.", body),

            Paragraph("Deine Karten", head),
            stats_row,
            chart,

        ]
        # Center the icon.
        story[0].hAlign = "CENTER"

        c = Canvas(str(out), pagesize=A5)
        c.setTitle(f"{app_name} – Anleitung")
        w, h = A5
        frame = Frame(MARGIN, MARGIN, w - 2 * MARGIN, h - 2 * MARGIN,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        frame.addFromList(story, c)
        if story:
            sys.exit(f"Manual doesn't fit on one A5 page ({len(story)} blocks left over) — shorten the text.")
        # The closing line sits near the bottom of the page, with a strip below it left blank
        # for signing by hand.
        last = Paragraph(f"{escape(CLOSING)} "
                         f'<img src="{wink}" width="{wink_size * wink_w / wink_h:.2f}" '
                         f'height="{wink_size}" valign="-2.5"/>', closing)
        _, last_h = last.wrap(w - 2 * MARGIN, h)
        free = frame._y - frame._y1 - last_h - SIGNATURE_SPACE
        if free < 1.5 * mm:
            sys.exit(f"Only {free / mm:.0f} mm between the text and the closing line — shorten the text.")
        last.drawOn(c, MARGIN, MARGIN + SIGNATURE_SPACE)
        c.save()
    return out


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(f"Wrote {build(sys.argv[1])}")


if __name__ == "__main__":
    main()
