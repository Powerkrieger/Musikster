package com.example.musikster

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

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

    val scanPlay = ScanPlayViewModel(deckRepository, viewModelScope, playbackManager)

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

    private val _deckCardCount = MutableStateFlow(deckRepository.loadDeck()?.cards?.size)
    val deckCardCount: StateFlow<Int?> = _deckCardCount.asStateFlow()

    private val _deckImportMessage = MutableStateFlow<String?>(null)
    val deckImportMessage: StateFlow<String?> = _deckImportMessage.asStateFlow()

    /** Reads [uri] (from a system file picker) and, if it's a valid deck.json, makes it the active deck. */
    fun importDeck(uri: Uri) {
        viewModelScope.launch {
            val json = try {
                getApplication<Application>().contentResolver.openInputStream(uri)
                    ?.bufferedReader()?.use { it.readText() }
            } catch (e: Exception) {
                null
            }
            val imported = json != null && deckRepository.importDeck(json)
            _deckImportMessage.value = if (imported) {
                "Deck imported!"
            } else {
                "Couldn't read that file — make sure it's a deck.json file."
            }
            _deckCardCount.value = deckRepository.loadDeck()?.cards?.size
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

    fun goHome() {
        playbackManager.pause()
        scanPlay.retryScanning()
        _appMode.value = AppMode.Home
    }

    fun openScanPlay() { _appMode.value = AppMode.ScanPlay }

    override fun onCleared() {
        super.onCleared()
        playbackManager.disconnect()
    }
}
