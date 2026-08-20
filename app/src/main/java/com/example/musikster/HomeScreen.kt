package com.example.musikster

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
fun HomeScreen(
    isRemoteConnected: Boolean,
    errorMessage: String?,
    deckCardCount: Int?,
    deckImportMessage: String?,
    onPlay: () -> Unit,
    onImportDeck: () -> Unit,
    onLogoutSpotify: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        Text(
            stringResource(R.string.birthday_message),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(40.dp))

        Button(onClick = onPlay, enabled = isRemoteConnected, modifier = Modifier.fillMaxWidth()) {
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
        Text(
            if (deckCardCount != null) "Deck loaded — $deckCardCount cards" else "No deck loaded yet",
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onImportDeck, modifier = Modifier.fillMaxWidth()) {
            Text(if (deckCardCount != null) "Import a Different Deck" else "Import Deck")
        }
        if (deckImportMessage != null) {
            Spacer(Modifier.height(8.dp))
            Text(deckImportMessage, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
        }
    }
}
