package de.powerizzle.musikster

import org.json.JSONObject

/**
 * One physical card. [cardId] is the short string encoded in the card's QR code —
 * deliberately not the Spotify URI, so a generic QR scanner app can't spoil the
 * answer, and the app can look up the card offline via [DeckRepository].
 *
 * Card ids must be unique across every deck that can be in play together, since
 * several people's decks can be shuffled into one game (see [DeckRepository]).
 * scripts/build_deck.py prefixes them with the person's slug ("nils-001") for
 * that reason; only the very first deck predates this and uses bare "001".
 */
data class Card(
    val cardId: String,
    val spotifyTrackId: String,
    val spotifyUri: String,
    val name: String,
    val artist: String,
    val year: Int?,
    val albumArtUrl: String?
) {
    companion object {
        fun fromJson(json: JSONObject): Card = Card(
            cardId = json.getString("cardId"),
            spotifyTrackId = json.getString("spotifyTrackId"),
            spotifyUri = json.getString("spotifyUri"),
            name = json.getString("name"),
            artist = json.getString("artist"),
            year = if (json.isNull("year")) null else json.getInt("year"),
            albumArtUrl = if (json.isNull("albumArtUrl")) null else json.getString("albumArtUrl")
        )
    }
}

/**
 * One person's deck. [deckId] identifies it across imports (re-importing a deck with the
 * same id replaces the previous copy); [name] is what the Home screen's deck list shows.
 * Both are optional in the JSON for compatibility with deck.json files written before
 * decks had identities — those fall back to the playlist id.
 */
data class Deck(
    val deckId: String,
    val name: String,
    val createdAt: Long,
    val playlistId: String,
    val cards: List<Card>
) {
    companion object {
        fun legacyDeckId(playlistId: String) = "playlist-$playlistId"

        fun fromJson(json: JSONObject): Deck {
            val playlistId = json.getString("playlistId")
            val deckId = json.optString("deckId").ifEmpty { legacyDeckId(playlistId) }
            return Deck(
                deckId = deckId,
                name = json.optString("name").ifEmpty { deckId },
                createdAt = json.getLong("createdAt"),
                playlistId = playlistId,
                cards = json.getJSONArray("cards").let { arr ->
                    (0 until arr.length()).map { Card.fromJson(arr.getJSONObject(it)) }
                }
            )
        }
    }
}
