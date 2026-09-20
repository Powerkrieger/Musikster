package de.powerizzle.musikster

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
fun HomeScreen(
    isRemoteConnected: Boolean,
    errorMessage: String?,
    decks: List<LoadedDeck>,
    conflictingCardIds: Set<String>,
    deckImportMessage: String?,
    onPlay: () -> Unit,
    onSetDeckEnabled: (deckId: String, enabled: Boolean) -> Unit,
    onRemoveDeck: (deckId: String) -> Unit,
    onImportDeck: () -> Unit,
    onLogoutSpotify: () -> Unit
) {
    val cardsInPlay = decks.filter { it.enabled }.sumOf { it.deck.cards.size }
    val canPlay = isRemoteConnected && cardsInPlay > 0

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        Text(
            stringResource(R.string.greeting),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(40.dp))

        Button(onClick = onPlay, enabled = canPlay, modifier = Modifier.fillMaxWidth()) {
            Text("Play")
        }

        if (!isRemoteConnected) {
            Spacer(Modifier.height(8.dp))
            Text("Connecting to Spotify app…", style = MaterialTheme.typography.bodySmall)
        }
        if (errorMessage != null) {
            Spacer(Modifier.height(8.dp))
            Text(errorMessage, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
        if (!isRemoteConnected) {
            Spacer(Modifier.height(4.dp))
            TextButton(onClick = onLogoutSpotify) {
                Text("Log Out of Spotify", style = MaterialTheme.typography.bodySmall)
            }
        }

        Spacer(Modifier.height(32.dp))
        DeckList(
            decks = decks,
            cardsInPlay = cardsInPlay,
            conflictingCardIds = conflictingCardIds,
            onSetDeckEnabled = onSetDeckEnabled,
            onRemoveDeck = onRemoveDeck
        )
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onImportDeck, modifier = Modifier.fillMaxWidth()) {
            Text(if (decks.isEmpty()) "Import Deck" else "Import Another Deck")
        }
        if (deckImportMessage != null) {
            Spacer(Modifier.height(8.dp))
            Text(deckImportMessage, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
        }
    }
}

/**
 * Every deck the app has, each with a switch for whether its cards are in play. Several
 * people's decks can be shuffled together physically; this is where the phone is told
 * which ones to recognise. Imported decks can be removed; the built-in one only disabled.
 */
@Composable
private fun DeckList(
    decks: List<LoadedDeck>,
    cardsInPlay: Int,
    conflictingCardIds: Set<String>,
    onSetDeckEnabled: (deckId: String, enabled: Boolean) -> Unit,
    onRemoveDeck: (deckId: String) -> Unit
) {
    Text(
        when {
            decks.isEmpty() -> "No deck loaded yet"
            decks.size == 1 -> "$cardsInPlay cards in play"
            else -> "$cardsInPlay cards in play from ${decks.count { it.enabled }} of ${decks.size} decks"
        },
        style = MaterialTheme.typography.bodySmall
    )
    if (conflictingCardIds.isNotEmpty()) {
        Spacer(Modifier.height(4.dp))
        Text(
            "Warning: ${conflictingCardIds.size} card ids appear in more than one deck in play — " +
                "scanning those cards will play the wrong song. Switch one of the decks off.",
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center
        )
    }
    decks.forEach { loaded ->
        Spacer(Modifier.height(8.dp))
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(loaded.deck.name, style = MaterialTheme.typography.bodyLarge)
                Text(
                    "${loaded.deck.cards.size} cards · " +
                        if (loaded.source == DeckSource.Bundled) "built in" else "imported",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.8f)
                )
            }
            if (loaded.source == DeckSource.Imported) {
                TextButton(onClick = { onRemoveDeck(loaded.id) }) {
                    Text("Remove", style = MaterialTheme.typography.bodySmall)
                }
                Spacer(Modifier.width(4.dp))
            }
            Switch(
                checked = loaded.enabled,
                onCheckedChange = { enabled -> onSetDeckEnabled(loaded.id, enabled) }
            )
        }
    }
}
