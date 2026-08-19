# [name]'s Musikster

A personalized [Hitster](https://hitstergame.com/)-style party game, built for [name]'s birthday.
Physical cards (one per song, printed from the app) + a phone that plays the song and reveals
the answer. Players build a timeline by guessing each song's release year — the app never shows
the answer on screen, so it's safe to have visible on the table.

---

## Setup (required before first build/run)

### 1. Spotify Developer Dashboard
Go to https://developer.spotify.com/dashboard and create an app.

Under **Settings → Edit**, add:
- **Redirect URIs:**
  - `musikster://callback` (the Android app's login)
  - `http://127.0.0.1:8927/callback` (the deck-building script's login — see below)
- **Android Package Name:** `com.example.musikster`
- **Android Package Fingerprint (SHA-1):** `3A:72:CE:FB:A5:96:66:48:DC:69:81:B6:96:B6:0C:4E:76:E7:99:00`
  *(debug keystore fingerprint — same machine-wide `~/.android/debug.keystore` used by QuickMusicQuiz.
  Use your release keystore's SHA-1 instead for a release build.)*

### 2. Fill in your Client ID
Add it to `local.properties` (already gitignored, never committed):
```
SPOTIFY_CLIENT_ID=your_client_id_here
```
Gradle exposes this as `BuildConfig.SPOTIFY_CLIENT_ID`, read by `SpotifyAuthManager.kt` — no
client ID ever lives in source. `scripts/build_deck.py` reads the same value straight out of
`local.properties`, so it only needs to be set once.

### 3. Spotify App Remote AAR
Already included in `app/libs/spotify-app-remote-release-0.8.0.aar` (copied from the QuickMusicQuiz
project). If you ever need to update it, download a newer release from
https://github.com/spotify/android-sdk/releases and replace the file (update the filename
reference in `app/build.gradle.kts` too if the version changes).

### 4. Build the deck
Deck building happens **outside the app**, once, on your computer — see
[Building the deck](#building-the-deck) below. The app just plays a deck that's already baked in.

### 5. Personalize it for [name]
A few things are deliberately left as placeholders for you to fill in:
- `app/src/main/res/values/strings.xml` — `birthday_message`
- `app/src/main/java/com/example/musikster/ui/theme/Color.kt` — accent colors (currently
  the default Compose template purple/pink; swap in her favorite color)

---

## Building the deck

A one-time (or whenever-the-playlist-changes) script, not part of the app:

```
cd scripts
uv run build_deck.py <playlist URL or ID>
```

(`uv run` installs the pinned dependencies from `scripts/pyproject.toml`/`uv.lock` into a local
`.venv` on first run — see https://docs.astral.sh/uv/ if you don't have `uv` installed.)

1. It opens your browser for a one-time Spotify login (same client id/account as the app), then
   reads every track in the playlist via the Spotify Web API.
2. It looks up each song's release year via the free iTunes Search API. Some matches are wrong
   (reissues, compilations, etc.) — put corrections in `scripts/overrides.csv` (`key,year` rows,
   where `key` is either the Spotify track id or `Song Name|Artist Name`) and rerun.
3. It writes **`app/src/main/assets/deck.json`** directly — this is what ships inside the APK, so
   **rebuild and reinstall the app** after running the script to pick up a new/changed deck.
4. It renders a printable PDF to `deck_output/musikster_deck.pdf`. Print it, then cut the
   cards out (see Printing notes below).

**Card design:** the QR-code (front) side is standardized — plain white, only the QR code itself
changes card to card. Drop a square-ish photo at `scripts/face.png` and it's composited
into the center of every QR code (high error-correction is used so the code still scans with the
photo covering the middle). Without that file, the QR is plain. The answer (back) side keeps the
pastel yellow-to-pink gradient with title/artist/year.

Because the deck now lives in the APK's assets, reinstalling the app (same build) restores it —
there's no separate backup step needed anymore.

**Sending the deck to someone else's build:** `deck.json` is gitignored (it's a personal playlist,
not source), so anyone who builds the app from a clone of this repo — e.g. [name] herself — won't
have it baked in. Instead of rebuilding, just send them the generated
`app/src/main/assets/deck.json` file (AirDrop, email, whatever); the app's Home screen has an
**"Import Deck"** button that opens a file picker, validates the file, and stores it in app-private
storage, overriding the bundled one immediately — no rebuild/reinstall needed. See
`app/src/main/java/com/example/musikster/DeckRepository.kt`.

**Bulk-adding tracks:** `scripts/add_to_playlist.py` adds a batch of tracks to a playlist you own,
without leaving the terminal — handy when you've curated a list faster than you can add them by
hand in Spotify. Put `artist,title` pairs (one per line) in a CSV and run:
```
uv run add_to_playlist.py <playlist URL or ID> tracks.csv
```
It searches Spotify for each pair, shows you what it resolved to, skips anything already in the
playlist, and asks for confirmation before writing anything. Rerun `build_deck.py` afterwards to
pick up the additions.

**Play**
1. Scan a card's QR-code side with the in-app camera.
2. The song plays through the Spotify app on this phone (App Remote SDK — needs Spotify Premium
   and the Spotify app installed). Pause/resume from here.
3. Players place the card in the timeline by guessing the year, then flip it to check the printed
   answer — the app screen never shows it.
4. **Scan Next Card** to continue.

---

## Printing notes

- Cards print as a 3×4 grid per A4 page (12 cards/page), with light gray cut guides. Front
  (QR) sheets are plain white; back (answer) sheets use the pastel yellow-to-pink gradient.
- Back sheets have their card columns mirrored, so a standard duplex print job set to
  **"flip on long edge"** should line up each card's QR side with its answer side once cut out.
  **Print a single page first** and check alignment before committing to the whole deck — this
  can't be verified without a real printer, and printers vary in their default duplex flip
  direction. If your printer instead flips on the short edge, mirror the rows instead of the
  columns (swap the `reversed()` grouping in `scripts/build_deck.py`'s `generate_pdf()` from
  per-row to per-column).

---

## Known limitations

- iTunes' free search API has an informal rate limit; looking up ~100 songs' release years is
  paced with a small delay and can take a few minutes.
- No digital timeline/scoring — by design, players self-referee like the real board game.

## Architecture

Same deliberately simple shape as `QuickMusicQuiz`: one Activity, Jetpack Compose, no DI, no
navigation library. `MainViewModel` holds a sealed `AppMode` and owns `ScanPlayViewModel` (a plain
state-holder class sharing its coroutine scope, not a separate Android ViewModel) — avoids a
custom `ViewModelProvider.Factory` for what's a single-screen-per-mode app. Deck building
(playlist fetch, year lookup, QR/PDF generation) lives entirely in `scripts/build_deck.py`, not in
the app — see [Building the deck](#building-the-deck).

| File | Purpose |
|---|---|
| `MainActivity.kt` | Single activity; root Compose UI; App Remote + OAuth redirect lifecycle |
| `MainViewModel.kt` | Top-level `AppMode` state; auth; owns the managers below |
| `SpotifyAuthManager.kt` | PKCE OAuth; token storage |
| `SpotifyPlaybackManager.kt` | App Remote SDK wrapper (play/pause/seek/art) |
| `DeckModels.kt` / `DeckRepository.kt` | Card/Deck data + loading the bundled `assets/deck.json`, or an imported one if present |
| `ScanPlayViewModel.kt` | QR scan → playback state machine |
| `HomeScreen.kt` / `ScanScreen.kt` / `PlaybackScreen.kt` | Compose screens |
| `scripts/build_deck.py` | Standalone deck builder: playlist fetch, year lookup, QR/PDF generation |

## AI notice
Code co-authored by Claude Code, adapted from the QuickMusicQuiz reference project.
