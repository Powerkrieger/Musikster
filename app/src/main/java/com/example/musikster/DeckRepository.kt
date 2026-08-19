package com.example.musikster

import android.content.Context
import java.io.File
import org.json.JSONObject

/**
 * Loads the active [Deck], preferring one imported at runtime (see [importDeck])
 * over the one bundled at build time as app/src/main/assets/deck.json. deck.json
 * is gitignored (it's [name]'s personal playlist), so anyone building from source
 * — e.g. [name] herself — won't have it baked in; instead whoever built the deck
 * can just send over the deck.json file and it's imported from Home without a
 * rebuild. QR codes only carry a card id, never track data, so this is what scans
 * are looked up against.
 */
class DeckRepository(private val context: Context) {

    private val importedFile: File
        get() = File(context.filesDir, "deck.json")

    fun loadDeck(): Deck? {
        val json = readImported() ?: readBundled() ?: return null
        return try {
            Deck.fromJson(JSONObject(json))
        } catch (e: Exception) {
            null
        }
    }

    fun findCard(cardId: String): Card? = loadDeck()?.cards?.find { it.cardId == cardId }

    /** Validates [json] parses as a [Deck], then persists it as the active deck. */
    fun importDeck(json: String): Boolean {
        return try {
            Deck.fromJson(JSONObject(json))
            importedFile.writeText(json)
            true
        } catch (e: Exception) {
            false
        }
    }

    private fun readImported(): String? =
        if (importedFile.exists()) importedFile.readText() else null

    private fun readBundled(): String? = try {
        context.assets.open("deck.json").bufferedReader().use { it.readText() }
    } catch (e: Exception) {
        null
    }
}
