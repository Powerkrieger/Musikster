# Archived scripts

Earlier 3D-print helpers that the game no longer needs, kept for reference. Each still runs
with `uv run <script>` from this directory (they resolve paths relative to the repo root);
see the docstring at the top of each for usage.

- `make_card_box.py`, `make_game_token.py` — a first, generated card box (tray + sleeve) and
  a lettered game token. Superseded by the hand-made models in `3d/` and
  `scripts/make_box.py` / `scripts/make_tokens.py`, which engrave the person's name/initial.
  They write into `stl/` at the repo root (gitignored).
- `make_heightmap.py`, `make_contour.py`, `vectorize_contour.py`, `make_coin.py`,
  `make_engraved_coin.py`, `make_plaque.py` — a photo-to-relief pipeline (portrait medallion
  and plaque) for a one-off keepsake: photo → height map / contour → embossed or engraved
  STL in `people/<slug>/stl/`. Not part of the game itself.
