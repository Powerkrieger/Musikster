package de.powerizzle.musikster

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.powerizzle.musikster.ui.theme.CardBackgroundPalette
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed class AppMode {
    object NotConnected : AppMode()
    object Authenticating : AppMode()
    object Home : AppMode()
    object ScanPlay : AppMode()
}

/**
 * Single top-level ViewModel driving the whole app, mirroring QuickMusicQuiz's
 * MainViewModel shape (sealed state, no DI, no navigation library). Owns the
 * Spotify managers plus the "sub-viewmodel" (a plain class, see
 * ScanPlayViewModel) that shares this ViewModel's scope. Deck building lives
 * outside the app entirely now — see scripts/build_deck.py.
 */
class MainViewModel(application: Application) : AndroidViewModel(application) {

    val authManager = SpotifyAuthManager(application)
    val playbackManager = SpotifyPlaybackManager(application)
    val deckRepository = DeckRepository(application)

    val scanPlay = ScanPlayViewModel(
        deckRepository,
        viewModelScope,
        playbackManager,
        onRoundStart = { rerollBackgroundGradient() }
    )

    private val _appMode = MutableStateFlow<AppMode>(
        if (authManager.isAuthenticated()) AppMode.Home else AppMode.NotConnected
    )
    val appMode: StateFlow<AppMode> = _appMode.asStateFlow()

    private val _isAppRemoteConnected = MutableStateFlow(false)
    val isAppRemoteConnected: StateFlow<Boolean> = _isAppRemoteConnected.asStateFlow()

    private val _authUrl = MutableStateFlow<String?>(null)
    val authUrl: StateFlow<String?> = _authUrl.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    /** Every deck the app knows about (bundled + imported), in Home-screen order. */
    private val _decks = MutableStateFlow<List<LoadedDeck>>(emptyList())
    val decks: StateFlow<List<LoadedDeck>> = _decks.asStateFlow()

    /** Card ids shared by two enabled decks — a warning on Home, see DeckRepository. */
    private val _conflictingCardIds = MutableStateFlow<Set<String>>(emptySet())
    val conflictingCardIds: StateFlow<Set<String>> = _conflictingCardIds.asStateFlow()

    private val _deckImportMessage = MutableStateFlow<String?>(null)
    val deckImportMessage: StateFlow<String?> = _deckImportMessage.asStateFlow()

    init {
        refreshDecks()
    }

    private fun refreshDecks() {
        viewModelScope.launch {
            val (decks, conflicts) = withContext(Dispatchers.IO) {
                deckRepository.loadDecks() to deckRepository.conflictingCardIds()
            }
            _decks.value = decks
            _conflictingCardIds.value = conflicts
        }
    }

    // A new two-color gradient (packed ARGB Longs) is picked from this palette at the start of
    // each round, mirroring QuickMusicQuiz's per-round background color.
    private val _backgroundGradient = MutableStateFlow(randomGradient())
    val backgroundGradient: StateFlow<Pair<Long, Long>> = _backgroundGradient.asStateFlow()

    private fun randomGradient(): Pair<Long, Long> {
        val (a, b) = CardBackgroundPalette.shuffled().take(2)
        return a to b
    }

    private fun rerollBackgroundGradient() {
        _backgroundGradient.value = randomGradient()
    }

    /**
     * Reads [uri] (from a system file picker) and, if it's a valid deck.json — plain or
     * gzip-compressed (a plain .json.gz, not a .zip) — adds it to the decks in play.
     * Importing a deck with the same id as an existing one replaces that copy.
     */
    fun importDeck(uri: Uri) {
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                val bytes = try {
                    getApplication<Application>().contentResolver.openInputStream(uri)?.use { it.readBytes() }
                } catch (e: Exception) {
                    null
                }
                if (bytes == null) DeckImportResult.Invalid else deckRepository.importDeck(bytes)
            }
            _deckImportMessage.value = when (result) {
                is DeckImportResult.Success -> {
                    val verb = if (result.replacedExisting) "updated" else "added"
                    "${result.deck.name} $verb — ${result.deck.cards.size} cards."
                }
                DeckImportResult.Invalid ->
                    "Couldn't read that file — make sure it's a Musikster deck file (…-deck.json.gz or .json)."
            }
            refreshDecks()
        }
    }

    fun setDeckEnabled(deckId: String, enabled: Boolean) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { deckRepository.setEnabled(deckId, enabled) }
            refreshDecks()
        }
    }

    fun removeDeck(deckId: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { deckRepository.removeImported(deckId) }
            _deckImportMessage.value = null
            refreshDecks()
        }
    }

    fun clearDeckImportMessage() { _deckImportMessage.value = null }

    fun startAuth() {
        _appMode.value = AppMode.Authenticating
        _authUrl.value = authManager.buildAuthorizationUrl()
    }

    fun handleAuthRedirect(code: String) {
        viewModelScope.launch {
            val success = authManager.exchangeCodeForToken(code)
            _appMode.value = if (success) AppMode.Home else AppMode.NotConnected
        }
    }

    fun onAuthUrlConsumed() { _authUrl.value = null }

    /** Refreshes the access token if it's expired, then connects App Remote if that leaves
     * us authenticated — used from Activity.onStart() instead of the raw isAuthenticated()
     * check, so a session that expired while the app was backgrounded reconnects silently
     * instead of forcing the user back through the Spotify login screen. */
    fun reconnectAppRemote(onConnected: () -> Unit, onFailure: (String) -> Unit) {
        viewModelScope.launch {
            if (authManager.refreshTokenIfNeeded() && authManager.isAuthenticated()) {
                if (_appMode.value !is AppMode.Home && _appMode.value !is AppMode.ScanPlay) {
                    _appMode.value = AppMode.Home
                }
                playbackManager.connect(onConnected, onFailure)
            }
        }
    }

    fun onAppRemoteConnected() {
        _isAppRemoteConnected.value = true
    }

    fun onAppRemoteDisconnected() {
        _isAppRemoteConnected.value = false
    }

    fun onAppRemoteFailure(error: String) {
        _isAppRemoteConnected.value = false
        _errorMessage.value = "Spotify: $error"
    }

    fun clearError() { _errorMessage.value = null }

    /** Resets the Spotify connection/auth state only — leaves the imported decks alone. For
     * troubleshooting a stuck or errored Spotify connection without needing to clear the
     * app's storage (which would also wipe the imported decks, see DeckRepository), forcing
     * a full deck re-import along with the re-login. */
    fun logoutSpotify() {
        playbackManager.disconnect()
        authManager.clearTokens()
        _isAppRemoteConnected.value = false
        _errorMessage.value = null
        _appMode.value = AppMode.NotConnected
    }

    fun goHome() {
        playbackManager.pause()
        scanPlay.retryScanning()
        _appMode.value = AppMode.Home
    }

    fun openScanPlay() {
        rerollBackgroundGradient()
        _appMode.value = AppMode.ScanPlay
    }

    override fun onCleared() {
        super.onCleared()
        playbackManager.disconnect()
    }
}
