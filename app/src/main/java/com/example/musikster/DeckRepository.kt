package com.example.musikster

import android.content.Context
import org.json.JSONObject

/**
 * Loads the [Deck] bundled at build time as app/src/main/assets/deck.json —
 * generated offline by scripts/build_deck.py, not built in-app. QR codes only
 * carry a card id, never track data, so this asset is what scans are looked
 * up against; it ships inside the APK, so reinstalling the app restores it.
 */
class DeckRepository(private val context: Context) {

    private val deck: Deck? by lazy {
        try {
            val json = context.assets.open("deck.json").bufferedReader().use { it.readText() }
            Deck.fromJson(JSONObject(json))
        } catch (e: Exception) {
            null
        }
    }

    fun loadDeck(): Deck? = deck

    fun findCard(cardId: String): Card? = deck?.cards?.find { it.cardId == cardId }
}
