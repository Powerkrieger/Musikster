#!/usr/bin/env python3
"""
Bulk-adds tracks to a Spotify playlist you own — a companion to build_deck.py
(which is read-only). Reads (artist, title) pairs from a CSV file, searches
Spotify for each, shows what it resolved to, skips anything already in the
playlist, and asks for confirmation before adding the rest.

Usage:
    cd scripts
    uv run add_to_playlist.py <playlist_url_or_id> <tracks.csv> [--yes]

tracks.csv has one "artist,title" pair per line, e.g.:
    ABBA,Waterloo
    Boney M.,Rasputin

Requires SPOTIFY_CLIENT_ID (same source as build_deck.py: env var or
local.properties). Uses the same redirect URI (http://127.0.0.1:8927/callback),
just with playlist-modify-* scopes added on top.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# Reuse build_deck.py's PKCE login, playlist-id parsing, and client-id lookup verbatim.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_deck import read_client_id, extract_playlist_id, pkce_login, print_identity  # noqa: E402

SCOPES = (
    "playlist-modify-public playlist-modify-private "
    "playlist-read-private playlist-read-collaborative"
)


def load_tracks(csv_path: Path) -> list[tuple[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return [(row[0].strip(), row[1].strip()) for row in csv.reader(f) if len(row) >= 2 and row[0].strip()]


def spotify_get(url: str, access_token: str) -> dict:
    req = Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"Spotify API error: {e.code} {e.reason}\n{body}")


def fetch_existing_keys(playlist_id: str, access_token: str) -> set[str]:
    fields = "items(item(name,artists(name))),next"
    url = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        f"?limit=50&offset=0&fields={urlencode({'': fields})[1:]}"
    )
    keys = set()
    while url:
        data = spotify_get(url, access_token)
        for entry in data.get("items", []):
            track = entry.get("item")
            if not track:
                continue
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            keys.add(f"{track.get('name', '')}|{artists}".lower())
        url = data.get("next") or None
    return keys


def search_track(artist: str, title: str, access_token: str) -> dict | None:
    query = urlencode({"q": f"{artist} {title}", "type": "track", "limit": 5})
    url = f"https://api.spotify.com/v1/search?{query}"
    data = spotify_get(url, access_token)
    items = data.get("tracks", {}).get("items", [])
    return items[0] if items else None


def add_tracks(playlist_id: str, uris: list[str], access_token: str) -> None:
    req = Request(
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
        data=json.dumps({"uris": uris}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req) as resp:
            json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"Spotify API error adding tracks: {e.code} {e.reason}\n{body}")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--yes"]
    auto_yes = "--yes" in sys.argv[1:]
    if len(args) != 2:
        sys.exit("Usage: uv run add_to_playlist.py <playlist_url_or_id> <tracks.csv> [--yes]")

    client_id = read_client_id()
    playlist_id = extract_playlist_id(args[0])
    tracks_to_add = load_tracks(Path(args[1]))
    if not tracks_to_add:
        sys.exit(f"No tracks found in {args[1]} — expected 'artist,title' rows.")

    access_token = pkce_login(client_id, scopes=SCOPES)
    print_identity(access_token)

    meta = spotify_get(
        f"https://api.spotify.com/v1/playlists/{playlist_id}?fields=name,owner.id,collaborative",
        access_token,
    )
    print(f"  playlist: {meta.get('name')!r} owned by {meta.get('owner', {}).get('id')} "
          f"(collaborative={meta.get('collaborative')})")

    print("Reading existing playlist tracks (to skip duplicates)…")
    existing = fetch_existing_keys(playlist_id, access_token)

    to_add: list[tuple[str, str, str, str]] = []  # (artist, title, resolved_label, uri)
    for artist, title in tracks_to_add:
        result = search_track(artist, title, access_token)
        if not result:
            print(f"  NO MATCH: {artist} - {title}")
            continue
        found_artists = ", ".join(a["name"] for a in result.get("artists", []))
        found_name = result.get("name", "")
        key = f"{found_name}|{found_artists}".lower()
        if key in existing:
            print(f"  already in playlist: {found_artists} - {found_name}")
            continue
        label = f"{found_artists} - {found_name} ({result.get('album', {}).get('name', '')})"
        to_add.append((artist, title, label, result["uri"]))
        print(f"  will add [{result['id']}]: {label}")

    if not to_add:
        print("Nothing new to add.")
        return

    if auto_yes:
        answer = "y"
        print(f"\nAdd these {len(to_add)} tracks to the playlist? [y/N] y  (--yes passed)")
    else:
        answer = input(f"\nAdd these {len(to_add)} tracks to the playlist? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted, nothing added.")
        return

    add_tracks(playlist_id, [uri for *_, uri in to_add], access_token)
    print(f"Added {len(to_add)} tracks. Rerun build_deck.py to refresh deck.json.")


if __name__ == "__main__":
    main()
