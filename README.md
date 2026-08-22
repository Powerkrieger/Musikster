# [name]'s Musikster

A personalized [Hitster](https://hitstergame.com/)-style party game, built for [name]'s birthday.
Physical cards (one per song, printed from the app) + a phone that plays the song and reveals
the answer. Players build a timeline by guessing each song's release year — the app never shows
the answer on screen, so it's safe to have visible on the table.

---

This is a one-off personal project for one specific Spotify app/deck, not a template meant to be
forked and reconfigured — there's exactly one Spotify Client ID and one deck in play. The two
things kept out of the repo are [name]'s curated song list (`deck.json`) and her recipient's photo
(`face.png`), both gitignored; everything else (the Spotify app, the theming, the release
signing) is already set up and just needs a build.

## If you're [name] (just want to play)

No building, no Android Studio, no Spotify dashboard. Grab the newest APK from
[Releases](../../releases), install it, then use the **"Import Deck"** button on the Home screen
to load the `deck.json` file whoever set this up sent you (see
[Building the deck](#building-the-deck) below for where that file comes from).

## Developer setup (building from source)

### 1. Spotify Client ID
The app needs `BuildConfig.SPOTIFY_CLIENT_ID` (read by `SpotifyAuthManager.kt`) to talk to Spotify.
It comes from one of two places, whichever is set:
- **CI builds** (GitHub Actions, see `.github/workflows/build.yml`) read it from the
  `SPOTIFY_CLIENT_ID` repo secret — already configured, nothing to do for a normal release build.
- **Local builds** (Android Studio, or running `scripts/build_deck.py`) read it from
  `local.properties` (gitignored, never committed):
  ```
  SPOTIFY_CLIENT_ID=your_client_id_here
  ```
  Ask Joost for the value, or create your own app at https://developer.spotify.com/dashboard —
  under **Settings → Edit** you'd need:
  - **Redirect URIs:** `musikster://callback` (app login) and
    `http://127.0.0.1:8927/callback` (deck-building script login)
  - **Android Package Name:** `com.example.musikster`
  - **Android Package Fingerprint (SHA-1):** your keystore's SHA-1 (`~/.android/debug.keystore`
    for local debug builds; the release keystore's for anything you intend to distribute)

### 2. Spotify App Remote AAR
Already included in `app/libs/spotify-app-remote-release-0.8.0.aar` (copied from the QuickMusicQuiz
project). If you ever need to update it, download a newer release from
https://github.com/spotify/android-sdk/releases and replace the file (update the filename
reference in `app/build.gradle.kts` too if the version changes).

### 3. Build the deck
Deck building happens **outside the app**, once, on your computer — see
[Building the deck](#building-the-deck) below.

### 4. Personalization status
A couple of placeholders are still open (see the `TODO(Joost)` comments):
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
4. It renders three printable PDFs: `deck_output/musikster_deck.pdf` (the card front/back
   sheets), `deck_output/musikster_line_sheet.pdf` (the cutting guide, printed once on plain
   paper), and `deck_output/musikster_deck_with_line_sheet.pdf` (the deck with the cut guide
   appended as its last page, for sharing/printing as a single file). Print the deck, then cut the
   cards out against the line sheet (see Printing notes below).

**Card design:** the QR-code (front) side is standardized — plain white, only the QR code itself
changes card to card. Drop a square-ish photo at `scripts/face.png` and it's composited
into the center of every QR code (high error-correction is used so the code still scans with the
photo covering the middle). Without that file, the QR is plain. The answer (back) side keeps the
green-to-blue gradient with title/artist/year.

Because the deck now lives in the APK's assets, reinstalling the app (same build) restores it —
there's no separate backup step needed anymore.

**Sending the deck to someone else's build:** `deck.json` is gitignored (it's a personal playlist,
not source), so anyone who builds the app from a clone of this repo — e.g. [name] herself — won't
have it baked in. Instead of rebuilding, just send them the generated
`app/src/main/assets/deck.json` file (AirDrop, email, whatever); the app's Home screen has an
**"Import Deck"** button that opens a file picker, validates the file, and stores it in app-private
storage, overriding the bundled one immediately — no rebuild/reinstall needed. See
`app/src/main/java/com/example/musikster/DeckRepository.kt`.

It compresses well (mostly repetitive keys/URLs), so if you'd rather send a smaller file, gzip it
first — the import step transparently decompresses:
```
gzip -k app/src/main/assets/deck.json   # -> deck.json.gz, ~5x smaller
```
Send `deck.json.gz` instead; "Import Deck" auto-detects and decompresses it, no unzipping needed
on the other end. (Plain `.gz`, not a `.zip` archive.)

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

### Hiding the song title

The app itself never shows the answer, but *Spotify* does: while a track plays, the Spotify app
posts its own media notification naming the song, which is exactly what players are meant to
guess. No app can suppress another app's notification, so the fix is to keep it off-screen:
in `MainActivity.onCreate`, the game runs full-screen with the system bars hidden and the screen
kept awake — there's no status bar for the notification to appear in, and the phone never times
out into a lock screen showing the same media card. Swiping in from the screen edge still reveals
the bars, so this hides the title rather than locking the phone down.

Turning Spotify's notifications off in Android settings (Settings → Notifications → App
notifications → Spotify) looks like the cleaner fix, but it **doesn't work** — tried on the
Samsung/One UI game phone and the media card kept showing. It's driven by the MediaSession, not
by the app's notification permission, so the in-app full-screen approach is what actually does it.

---

## Printing notes

- Cards print as a 3×4 grid per A4 page (12 cards/page). Front (QR) sheets are plain white; back
  (answer) sheets use the green-to-blue gradient. `musikster_line_sheet.pdf` is a single
  page of light gray cut guides at the same grid positions — print it once on plain paper and lay
  each printed card sheet underneath it to cut against.
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
