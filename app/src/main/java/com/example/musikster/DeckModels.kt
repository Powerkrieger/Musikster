package com.example.musikster

import org.json.JSONObject

/**
 * One physical card. [cardId] is the short string encoded in the card's QR code —
 * deliberately not the Spotify URI, so a generic QR scanner app can't spoil the
 * answer, and the app can look up the card offline via [DeckRepository].
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

data class Deck(
    val createdAt: Long,
    val playlistId: String,
    val cards: List<Card>
) {
    companion object {
        fun fromJson(json: JSONObject): Deck = Deck(
            createdAt = json.getLong("createdAt"),
            playlistId = json.getString("playlistId"),
            cards = json.getJSONArray("cards").let { arr ->
                (0 until arr.length()).map { Card.fromJson(arr.getJSONObject(it)) }
            }
        )
    }
}
