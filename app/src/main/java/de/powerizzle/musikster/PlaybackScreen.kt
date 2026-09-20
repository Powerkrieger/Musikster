package de.powerizzle.musikster

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * Deliberately shows no track info — the physical card's back already has the
 * answer. This screen is just remote-control buttons for the song playing on
 * the shared Spotify app, safe to have visible to the whole table.
 */
@Composable
fun PlaybackScreen(
    state: ScanPlayState,
    onTogglePlayback: () -> Unit,
    onScanNext: () -> Unit,
    onRetry: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        when (state) {
            is ScanPlayState.Loading -> {
                CircularProgressIndicator()
                Spacer(Modifier.height(16.dp))
                Text("Starting playback…")
            }

            is ScanPlayState.Playing -> {
                Text("♫", style = MaterialTheme.typography.displayLarge)
                Spacer(Modifier.height(16.dp))
                Text(
                    if (state.isPaused) "Paused" else "Playing — guess the year!",
                    style = MaterialTheme.typography.titleLarge
                )
                Spacer(Modifier.height(32.dp))
                Button(onClick = onTogglePlayback, modifier = Modifier.fillMaxWidth()) {
                    Text(if (state.isPaused) "▶️  Resume" else "⏸️  Pause")
                }
                Spacer(Modifier.height(12.dp))
                OutlinedButton(onClick = onScanNext, modifier = Modifier.fillMaxWidth()) {
                    Text("Scan Next Card →")
                }
            }

            is ScanPlayState.CardNotFound -> {
                Text("Card not recognized", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(8.dp))
                Text(
                    "Scanned code \"${state.scannedId}\" isn't in the current deck.",
                    textAlign = TextAlign.Center
                )
                Spacer(Modifier.height(24.dp))
                Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) {
                    Text("Try Again")
                }
            }

            is ScanPlayState.Scanning -> Unit // handled by the camera screen
        }
    }
}
