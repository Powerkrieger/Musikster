package com.example.musikster

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * The app deliberately never shows a scanned card's title/artist/year on screen —
 * that's what flipping the physical card is for. This screen only plays/pauses
 * the audio, so a phone visible to the whole table can't spoil the round.
 */
sealed class ScanPlayState {
    object Scanning : ScanPlayState()
    object Loading : ScanPlayState()
    data class Playing(val cardId: String, val isPaused: Boolean) : ScanPlayState()
    data class CardNotFound(val scannedId: String) : ScanPlayState()
}

/** Owned by [MainViewModel] as a plain state-holder class sharing its coroutine scope. */
class ScanPlayViewModel(
    context: Context,
    private val scope: CoroutineScope,
    private val playbackManager: SpotifyPlaybackManager
) {
    private val deckRepository = DeckRepository(context)

    private val _state = MutableStateFlow<ScanPlayState>(ScanPlayState.Scanning)
    val state: StateFlow<ScanPlayState> = _state.asStateFlow()

    private var scanningEnabled = true

    fun hasDeck(): Boolean = deckRepository.loadDeck() != null

    /** Called with a QR payload once per physical scan; ignores repeats while a card is loading/playing. */
    fun onCardScanned(cardId: String) {
        if (!scanningEnabled) return
        scanningEnabled = false

        val card = deckRepository.findCard(cardId)
        if (card == null) {
            _state.value = ScanPlayState.CardNotFound(cardId)
            return
        }

        _state.value = ScanPlayState.Loading
        scope.launch {
            playbackManager.playTrackAt(card.spotifyUri, 0L)
            _state.value = ScanPlayState.Playing(card.cardId, isPaused = false)
        }
    }

    fun togglePlayback() {
        val playing = _state.value as? ScanPlayState.Playing ?: return
        if (playing.isPaused) {
            playbackManager.resume()
        } else {
            playbackManager.pause()
        }
        _state.value = playing.copy(isPaused = !playing.isPaused)
    }

    /** Stops the current track and returns to the scanner for the next card. */
    fun scanNext() {
        playbackManager.pause()
        scanningEnabled = true
        _state.value = ScanPlayState.Scanning
    }

    fun retryScanning() {
        scanningEnabled = true
        _state.value = ScanPlayState.Scanning
    }
}
